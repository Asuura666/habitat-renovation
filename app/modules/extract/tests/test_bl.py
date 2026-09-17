"""Tests de `bl.py` (L3-T2, module PUR).

Comme `test_confiance.py` (L3-T1), les variantes de la réponse OCR
synthétique sont construites en mémoire (`json.loads`/`json.dumps` du
`document_annotation`, jamais un second fichier fixture) : décision du
contrôleur. Toutes les valeurs sont inventées (`donnees/bl_synthetique.
mistral-ocr.json`, constat 3 du plan lot 3) : aucune donnée client.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.extract.bl import (
    CHAMPS_ENTETE_BL,
    CHAMPS_LIGNE_BL,
    CONSIGNE_ANNOTATION_BL,
    OPTIONS_OCR_BL,
    SCHEMA_ANNOTATION_BL,
    AnnotationIllisible,
    BLExtrait,
    DateLue,
    NombreLu,
    TexteLu,
    analyser_bl,
    date_bl,
    extraction_en_json,
    nombre_bl,
    normaliser_numero_bl,
)

_DONNEES = Path(__file__).parent / "donnees"


def _charger_reponse() -> dict[str, Any]:
    """Réponse OCR synthétique, relue à chaque appel (jamais partagée entre
    tests : une mutation dans un test ne doit pas fuiter vers un autre)."""
    reponse: dict[str, Any] = json.loads(
        (_DONNEES / "bl_synthetique.mistral-ocr.json").read_text(encoding="utf-8")
    )
    return reponse


def _reponse_avec_annotation(modif: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Réponse synthétique dont l'annotation est modifiée en mémoire (jamais
    un second fichier fixture, décision du contrôleur)."""
    reponse = _charger_reponse()
    annotation = json.loads(reponse["document_annotation"])
    modif(annotation)
    reponse["document_annotation"] = json.dumps(annotation)
    return reponse


def _vide() -> TexteLu:
    return TexteLu(brut=None, confiance=None)


def _bl_extrait_minimal(**overrides: Any) -> BLExtrait:
    """`BLExtrait` entièrement vide, pour ne tester que les champs qui
    comptent dans chaque test (édition via `overrides`)."""
    base: dict[str, Any] = {
        "type_bon": _vide(),
        "fournisseur": _vide(),
        "agence_fournisseur": _vide(),
        "siret": _vide(),
        "tva_intracommunautaire": _vide(),
        "numero": _vide(),
        "date_doc": DateLue(brut=None, valeur=None, confiance=None),
        "chantier_brut": _vide(),
        "numero_commande": _vide(),
        "enleve_par": _vide(),
        "total_ht": NombreLu(brut=None, valeur=None, confiance=None),
        "total_tva": NombreLu(brut=None, valeur=None, confiance=None),
        "total_ttc": NombreLu(brut=None, valeur=None, confiance=None),
        "lignes": (),
        "numero_detecte": None,
    }
    base.update(overrides)
    return BLExtrait(**base)


# --------------------------------------------------------------------------
# analyser_bl — réponse synthétique complète
# --------------------------------------------------------------------------


def test_analyser_bl_bl_synthetique_tous_les_champs_entete() -> None:
    extrait = analyser_bl(_charger_reponse())

    assert extrait.type_bon.brut == "livraison"
    assert extrait.fournisseur.brut == "PEINTURES EXEMPLE SAS"
    assert extrait.agence_fournisseur.brut == (
        "Agence Exempleville Nord - 12 rue Fictive 99000 Exempleville"
    )
    assert extrait.siret.brut == "000 000 000 00000"
    assert extrait.tva_intracommunautaire.brut == "FR00000000000"
    assert extrait.numero.brut == "L209900000123"
    assert extrait.date_doc.brut == "03/09/2026"
    assert extrait.date_doc.valeur == date(2026, 9, 3)
    assert extrait.chantier_brut.brut == "MAISON TEST (9900000001)"
    assert extrait.numero_commande.brut == "CDE-TEST-42"
    assert extrait.enleve_par.brut == "J. DUPONT"
    assert extrait.total_ht.valeur == Decimal("161.50")
    assert extrait.total_tva.valeur == Decimal("32.30")
    assert extrait.total_ttc.valeur == Decimal("193.80")


def test_analyser_bl_bl_synthetique_trois_lignes_converties() -> None:
    extrait = analyser_bl(_charger_reponse())

    assert len(extrait.lignes) == 3
    assert [ligne.ordre for ligne in extrait.lignes] == [0, 1, 2]

    premiere = extrait.lignes[0]
    assert premiere.code.brut == "AB1234"
    assert premiere.designation.brut == "ENDUIT EXEMPLE 25KG"
    assert premiere.quantite.valeur == Decimal("4")
    assert premiere.unite.brut == "SEAU"
    assert premiere.pu_ht.valeur == Decimal("31.50")
    assert premiere.montant_ht.valeur == Decimal("126.00")


def test_analyser_bl_bl_synthetique_numero_detecte() -> None:
    extrait = analyser_bl(_charger_reponse())

    assert extrait.numero_detecte is not None
    assert extrait.numero_detecte.numero == "L209900000123"


def test_analyser_bl_bl_synthetique_confiances_entete_non_nulles() -> None:
    extrait = analyser_bl(_charger_reponse())

    for nom in CHAMPS_ENTETE_BL:
        confiance = getattr(extrait, nom).confiance
        assert confiance is not None and confiance > Decimal("0"), nom


def test_analyser_bl_bl_synthetique_confiances_lignes_non_nulles() -> None:
    extrait = analyser_bl(_charger_reponse())

    for ligne in extrait.lignes:
        for nom in CHAMPS_LIGNE_BL:
            confiance = getattr(ligne, nom).confiance
            assert confiance is not None and confiance > Decimal("0"), (
                ligne.code.brut,
                nom,
            )


# --------------------------------------------------------------------------
# analyser_bl — annotation inexploitable
# --------------------------------------------------------------------------


def test_analyser_bl_annotation_absente_leve() -> None:
    reponse = _charger_reponse()
    del reponse["document_annotation"]

    with pytest.raises(AnnotationIllisible):
        analyser_bl(reponse)


def test_analyser_bl_annotation_null_leve() -> None:
    reponse = _charger_reponse()
    reponse["document_annotation"] = None

    with pytest.raises(AnnotationIllisible):
        analyser_bl(reponse)


def test_analyser_bl_annotation_json_invalide_leve() -> None:
    reponse = _charger_reponse()
    reponse["document_annotation"] = "{ceci n'est pas du JSON valide"

    with pytest.raises(AnnotationIllisible):
        analyser_bl(reponse)


def test_analyser_bl_annotation_json_non_objet_leve() -> None:
    reponse = _charger_reponse()
    reponse["document_annotation"] = json.dumps(["une", "liste", "pas", "un", "objet"])

    with pytest.raises(AnnotationIllisible):
        analyser_bl(reponse)


def test_analyser_bl_annotation_chaine_null_json_leve() -> None:
    """`document_annotation = "null"` (chaîne JSON) : décodée en `None`,
    donc non-objet -> `AnnotationIllisible` (pas une exception de décodage)."""
    reponse = _charger_reponse()
    reponse["document_annotation"] = "null"

    with pytest.raises(AnnotationIllisible):
        analyser_bl(reponse)


# --------------------------------------------------------------------------
# analyser_bl — annotation en dict, conversions, clés manquantes
# --------------------------------------------------------------------------


def test_analyser_bl_annotation_en_dict_acceptee() -> None:
    annotation: dict[str, Any] = {"fournisseur": "TEST DICT", "lignes": []}
    reponse: dict[str, Any] = {"document_annotation": annotation}

    extrait = analyser_bl(reponse)

    assert extrait.fournisseur.brut == "TEST DICT"


def test_analyser_bl_nombre_et_booleen_json_convertis_en_chaine() -> None:
    annotation: dict[str, Any] = {
        "numero": 12345,
        "type_bon": True,
        "lignes": [],
    }
    reponse: dict[str, Any] = {"document_annotation": annotation}

    extrait = analyser_bl(reponse)

    assert extrait.numero.brut == "12345"
    assert extrait.type_bon.brut == "True"


def test_analyser_bl_cles_manquantes_renvoient_none() -> None:
    reponse: dict[str, Any] = {"document_annotation": {"lignes": []}}

    extrait = analyser_bl(reponse)

    for nom in CHAMPS_ENTETE_BL:
        assert getattr(extrait, nom).brut is None, nom
    assert extrait.date_doc.valeur is None
    assert extrait.total_ht.valeur is None
    assert extrait.lignes == ()


def test_analyser_bl_chaine_blanche_renvoie_none() -> None:
    reponse: dict[str, Any] = {
        "document_annotation": {"fournisseur": "   ", "lignes": []}
    }

    extrait = analyser_bl(reponse)

    assert extrait.fournisseur.brut is None


def test_analyser_bl_reponse_sans_pages_confiances_toutes_none() -> None:
    """Décision du contrôleur : réponse sans `pages`, annotation lisible ->
    `BLExtrait` complet mais sans aucune confiance."""
    annotation: dict[str, Any] = {champ: "valeur" for champ in CHAMPS_ENTETE_BL}
    annotation["lignes"] = []
    reponse: dict[str, Any] = {"document_annotation": annotation}

    extrait = analyser_bl(reponse)

    for nom in CHAMPS_ENTETE_BL:
        assert getattr(extrait, nom).confiance is None, nom
    assert extrait.numero_detecte is None


# --------------------------------------------------------------------------
# analyser_bl — lignes : ignorées si entièrement nulles, ordre recalculé
# --------------------------------------------------------------------------


def test_analyser_bl_ligne_entierement_nulle_ignoree_ordre_recalcule() -> None:
    def modif(annotation: dict[str, Any]) -> None:
        annotation["lignes"].insert(1, dict.fromkeys(CHAMPS_LIGNE_BL))

    reponse = _reponse_avec_annotation(modif)

    extrait = analyser_bl(reponse)

    assert len(extrait.lignes) == 3
    assert [ligne.ordre for ligne in extrait.lignes] == [0, 1, 2]
    # La ligne insérée (nulle) a disparu : la 2e ligne gardée est CD5678,
    # comme dans la donnée d'origine.
    assert extrait.lignes[1].code.brut == "CD5678"


def test_analyser_bl_ligne_partiellement_nulle_gardee() -> None:
    def modif(annotation: dict[str, Any]) -> None:
        ligne_partielle = dict.fromkeys(CHAMPS_LIGNE_BL)
        ligne_partielle["code"] = "GH3456"
        annotation["lignes"].append(ligne_partielle)

    reponse = _reponse_avec_annotation(modif)

    extrait = analyser_bl(reponse)

    assert len(extrait.lignes) == 4
    assert extrait.lignes[3].code.brut == "GH3456"
    assert extrait.lignes[3].designation.brut is None


# --------------------------------------------------------------------------
# analyser_bl — valeur inventée par l'annotation : confiance 0
# --------------------------------------------------------------------------


def test_analyser_bl_valeur_inventee_absente_du_texte_confiance_zero() -> None:
    def modif(annotation: dict[str, Any]) -> None:
        annotation["enleve_par"] = "PERSONNE INVENTEE INTROUVABLE DANS LE TEXTE"

    reponse = _reponse_avec_annotation(modif)

    extrait = analyser_bl(reponse)

    assert extrait.enleve_par.brut == "PERSONNE INVENTEE INTROUVABLE DANS LE TEXTE"
    assert extrait.enleve_par.confiance == Decimal("0")


def test_analyser_bl_ligne_valeur_inventee_confiance_zero() -> None:
    def modif(annotation: dict[str, Any]) -> None:
        annotation["lignes"][0]["designation"] = "DESIGNATION INVENTEE INTROUVABLE"

    reponse = _reponse_avec_annotation(modif)

    extrait = analyser_bl(reponse)

    assert extrait.lignes[0].designation.confiance == Decimal("0")


# --------------------------------------------------------------------------
# nombre_bl
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("1 234,56", Decimal("1234.56")),
        ("31.50", Decimal("31.50")),
        ("4", Decimal("4")),
        ("-2,5", Decimal("-2.5")),
        ("1\u202f234,56", Decimal("1234.56")),
        ("1\xa0234,56", Decimal("1234.56")),
        ("  126,00  ", Decimal("126.00")),
    ],
)
def test_nombre_bl_valeurs_valides(brut: str, attendu: Decimal) -> None:
    assert nombre_bl(brut) == attendu


@pytest.mark.parametrize(
    "brut",
    [None, "", "   ", "abc", "1,2,3", "1.2.3", "12,,50", "quatre", "4X5", "12-50"],
)
def test_nombre_bl_valeurs_invalides(brut: str | None) -> None:
    assert nombre_bl(brut) is None


# --------------------------------------------------------------------------
# date_bl
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("03/09/2026", date(2026, 9, 3)),
        ("03/09/26", date(2026, 9, 3)),
        ("03.09.2026", date(2026, 9, 3)),
        ("03-09-2026", date(2026, 9, 3)),
    ],
)
def test_date_bl_valeurs_valides(brut: str, attendu: date) -> None:
    assert date_bl(brut) == attendu


@pytest.mark.parametrize(
    "brut",
    [
        None,
        "",
        "   ",
        "31/02/2026",
        "2026/09/03",
        "pas une date",
        "03/09/202",
        "03/13/2026",
    ],
)
def test_date_bl_valeurs_invalides(brut: str | None) -> None:
    assert date_bl(brut) is None


# --------------------------------------------------------------------------
# normaliser_numero_bl
# --------------------------------------------------------------------------


def test_normaliser_numero_bl() -> None:
    assert normaliser_numero_bl(" l 2099 ") == "L2099"
    assert normaliser_numero_bl(None) is None
    assert normaliser_numero_bl("   ") is None
    assert normaliser_numero_bl("l209900000123") == "L209900000123"


# --------------------------------------------------------------------------
# extraction_en_json
# --------------------------------------------------------------------------


def test_extraction_en_json_bl_synthetique_serialisable_et_types_convertis() -> None:
    extrait = analyser_bl(_charger_reponse())

    resultat = extraction_en_json(extrait)
    json.dumps(resultat)  # ne doit jamais lever

    assert resultat["version"] == 1
    assert resultat["champs"]["date_doc"]["brut"] == "03/09/2026"
    assert resultat["champs"]["date_doc"]["valeur"] == "2026-09-03"
    assert isinstance(resultat["champs"]["date_doc"]["confiance"], str)
    assert resultat["champs"]["total_ht"]["valeur"] == "161.50"
    assert resultat["champs"]["numero"]["valeur"] == "L209900000123"
    assert resultat["numero_detecte"] == "L209900000123"
    assert resultat["lignes"][0]["ordre"] == 0
    assert resultat["lignes"][0]["montant_ht"]["valeur"] == "126.00"
    assert resultat["lignes"][0]["quantite"]["valeur"] == "4"


def test_extraction_en_json_numero_normalise() -> None:
    extrait = _bl_extrait_minimal(numero=TexteLu(brut=" l 2099 ", confiance=None))

    resultat = extraction_en_json(extrait)

    assert resultat["champs"]["numero"]["brut"] == " l 2099 "
    assert resultat["champs"]["numero"]["valeur"] == "L2099"


def test_extraction_en_json_texte_espaces_multiples_reduits() -> None:
    extrait = _bl_extrait_minimal(
        chantier_brut=TexteLu(brut="MAISON   TEST  ", confiance=Decimal("0.9"))
    )

    resultat = extraction_en_json(extrait)

    assert resultat["champs"]["chantier_brut"]["brut"] == "MAISON   TEST  "
    assert resultat["champs"]["chantier_brut"]["valeur"] == "MAISON TEST"
    assert resultat["champs"]["chantier_brut"]["confiance"] == "0.9"


def test_extraction_en_json_valeurs_manquantes_serialisables() -> None:
    extrait = _bl_extrait_minimal()

    resultat = extraction_en_json(extrait)
    json.dumps(resultat)  # ne doit jamais lever

    assert resultat["champs"]["numero"] == {
        "brut": None,
        "valeur": None,
        "confiance": None,
    }
    assert resultat["champs"]["date_doc"] == {
        "brut": None,
        "valeur": None,
        "confiance": None,
    }
    assert resultat["numero_detecte"] is None
    assert resultat["lignes"] == []


# --------------------------------------------------------------------------
# SCHEMA_ANNOTATION_BL / CONSIGNE_ANNOTATION_BL / OPTIONS_OCR_BL
# --------------------------------------------------------------------------


def test_schema_annotation_bl_structure_stricte() -> None:
    json.dumps(SCHEMA_ANNOTATION_BL)  # ne doit jamais lever

    assert SCHEMA_ANNOTATION_BL["type"] == "object"
    assert SCHEMA_ANNOTATION_BL["additionalProperties"] is False
    assert set(SCHEMA_ANNOTATION_BL["required"]) == {*CHAMPS_ENTETE_BL, "lignes"}

    for nom in CHAMPS_ENTETE_BL:
        propriete = SCHEMA_ANNOTATION_BL["properties"][nom]
        assert propriete["type"] == ["string", "null"]
        assert isinstance(propriete["description"], str) and propriete["description"]

    lignes_schema = SCHEMA_ANNOTATION_BL["properties"]["lignes"]
    assert lignes_schema["type"] == "array"
    items = lignes_schema["items"]
    assert items["type"] == "object"
    assert items["additionalProperties"] is False
    assert set(items["required"]) == set(CHAMPS_LIGNE_BL)
    for nom in CHAMPS_LIGNE_BL:
        propriete = items["properties"][nom]
        assert propriete["type"] == ["string", "null"]
        assert isinstance(propriete["description"], str) and propriete["description"]


def test_options_ocr_bl_serialisable_et_strict() -> None:
    json.dumps(OPTIONS_OCR_BL)  # ne doit jamais lever

    assert OPTIONS_OCR_BL["confidence_scores_granularity"] == "word"
    annotation_format = OPTIONS_OCR_BL["document_annotation_format"]
    assert annotation_format["type"] == "json_schema"
    json_schema = annotation_format["json_schema"]
    assert json_schema["name"] == "bon_de_livraison"
    assert json_schema["strict"] is True
    assert json_schema["schema"] is SCHEMA_ANNOTATION_BL
    assert OPTIONS_OCR_BL["document_annotation_prompt"] == CONSIGNE_ANNOTATION_BL
    assert CONSIGNE_ANNOTATION_BL  # jamais vide
