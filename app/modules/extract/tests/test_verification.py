"""Tests de `verification.py` (L3-T3, module PUR).

Comme `test_bl.py`/`test_confiance.py`, toutes les données sont inventées :
soit construites directement en `BLAVerifier`/`Facture` (la plupart des
tests, qui n'ont pas besoin d'une réponse OCR complète), soit relues depuis
`donnees/bl_synthetique.mistral-ocr.json` (constat 3, aucune donnée client)
pour le test d'intégration `bl_a_verifier` -> `verifier_bl`. Un dernier test
relit, s'il existe, la fixture réelle `tests/fixtures/unikalo/
facture_2026-08.mistral-ocr.json` (absente dans cet arbre de travail,
décision du contrôleur) et ne compare qu'une égalité, jamais une valeur.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.extract.bl import (
    AnnotationIllisible,
    BLExtrait,
    DateLue,
    LigneBL,
    NombreLu,
    TexteLu,
    analyser_bl,
)
from app.modules.extract.facture import BlocBL, Facture, LigneFacture, TypeLigne
from app.modules.extract.ocr import NumeroBL, TypeBL
from app.modules.extract.unikalo import analyser_facture_unikalo
from app.modules.extract.verification import (
    CHAMPS_OBLIGATOIRES_BL,
    SEUIL_CONFIANCE_DEFAUT,
    TOLERANCE_TOTAL_DEFAUT,
    BLAVerifier,
    CodeMotif,
    LigneAVerifier,
    Motif,
    bl_a_verifier,
    motif_depuis_json,
    motif_en_json,
    verifier_bl,
    verifier_facture,
)

_DONNEES = Path(__file__).parent / "donnees"

# --------------------------------------------------------------------------
# Constructeurs de données inventées
# --------------------------------------------------------------------------


def _bl_valide(**overrides: Any) -> BLAVerifier:
    """`BLAVerifier` sans aucun motif attendu de `verifier_bl` (seuil et
    tolérance par défaut) : tous les champs obligatoires présents, une ligne
    dont le montant égale `total_ht` (L3-D25 : depuis L3-T6b, `total_ht`
    absent ou aucune ligne déclenchent toujours un motif, la ligne par
    défaut évite de contaminer les tests qui ne s'intéressent pas à
    `TOTAL_ABSENT`/`LIGNES_ABSENTES`), confiances toutes au-dessus du seuil,
    numéro détecté identique au numéro lu. Chaque test override seulement ce
    qui l'intéresse."""
    base: dict[str, Any] = {
        "fournisseur": "FOURNISSEUR INVENTE",
        "numero": "BL0001",
        "date_doc": date(2026, 1, 15),
        "chantier_brut": "CHANTIER INVENTE",
        "total_ht": Decimal("10.00"),
        "lignes": (
            LigneAVerifier(
                ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.95")
            ),
        ),
        "confiances": {
            "fournisseur": Decimal("0.95"),
            "numero": Decimal("0.95"),
            "date_doc": Decimal("0.95"),
            "chantier_brut": Decimal("0.95"),
            "total_ht": Decimal("0.95"),
        },
        "illisibles": frozenset(),
        "numero_detecte": "BL0001",
    }
    base.update(overrides)
    return BLAVerifier(**base)


def _confiances(**overrides: Decimal | None) -> dict[str, Decimal | None]:
    """Confiances par défaut (toutes à 0,95), avec les overrides demandés
    — évite de dépendre du type exact de `BLAVerifier.confiances`
    (`Mapping`, pas forcément un `dict`) dans les tests."""
    base: dict[str, Decimal | None] = {
        "fournisseur": Decimal("0.95"),
        "numero": Decimal("0.95"),
        "date_doc": Decimal("0.95"),
        "chantier_brut": Decimal("0.95"),
        "total_ht": Decimal("0.95"),
    }
    base.update(overrides)
    return base


def _verifier(bl: BLAVerifier) -> tuple[Motif, ...]:
    return verifier_bl(
        bl, seuil_confiance=SEUIL_CONFIANCE_DEFAUT, tolerance=TOLERANCE_TOTAL_DEFAUT
    )


def _codes(motifs: tuple[Motif, ...]) -> set[CodeMotif]:
    return {m.code for m in motifs}


def _ligne_facture(montant: Decimal | None, ordre: int = 0) -> LigneFacture:
    return LigneFacture(
        ordre=ordre,
        type_ligne=TypeLigne.ARTICLE,
        code_article="ART0001",
        designation="ARTICLE INVENTE",
        qte_livree=Decimal("1"),
        qte_totale=Decimal("1"),
        unite=None,
        pu_ht=montant,
        pu_cdt=None,
        remise_pct=None,
        montant_ht=montant,
        tva=Decimal("20"),
    )


def _facture(total_ht: Decimal, *montants_lignes: Decimal | None) -> Facture:
    lignes = tuple(
        _ligne_facture(montant, ordre) for ordre, montant in enumerate(montants_lignes)
    )
    bloc = BlocBL(
        numero_bl="BL0001",
        date_bl=date(2026, 1, 15),
        numero_commande=None,
        chantier_brut="CHANTIER INVENTE",
        lignes=lignes,
    )
    return Facture(
        fournisseur_brut="FOURNISSEUR INVENTE",
        numero="FAC0001",
        date_facture=date(2026, 1, 20),
        client=None,
        echeance=None,
        total_ht=total_ht,
        blocs=(bloc,),
    )


# --------------------------------------------------------------------------
# verifier_bl — cas de base sans motif
# --------------------------------------------------------------------------


def test_verifier_bl_document_valide_aucun_motif() -> None:
    assert _verifier(_bl_valide()) == ()


# --------------------------------------------------------------------------
# CHAMP_ABSENT
# --------------------------------------------------------------------------


@pytest.mark.parametrize("champ", CHAMPS_OBLIGATOIRES_BL)
def test_champ_absent_declenche_pour_chaque_champ_obligatoire(champ: str) -> None:
    motifs = _verifier(_bl_valide(**{champ: None}))

    assert (
        Motif(code=CodeMotif.CHAMP_ABSENT, champ=champ, detail={"champ": champ})
        in motifs
    )


def test_champ_absent_ne_declenche_pas_si_present() -> None:
    motifs = _verifier(_bl_valide())

    assert CodeMotif.CHAMP_ABSENT not in _codes(motifs)


# --------------------------------------------------------------------------
# VALEUR_ILLISIBLE
# --------------------------------------------------------------------------


def test_valeur_illisible_declenche_pour_un_champ_obligatoire_illisible() -> None:
    bl = _bl_valide(date_doc=None, illisibles=frozenset({"date_doc"}))

    motifs = _verifier(bl)

    assert (
        Motif(
            code=CodeMotif.VALEUR_ILLISIBLE,
            champ="date_doc",
            detail={"champ": "date_doc"},
        )
        in motifs
    )
    # L'illisibilité prime sur l'absence : pas de CHAMP_ABSENT en double.
    assert not any(
        m.code is CodeMotif.CHAMP_ABSENT and m.champ == "date_doc" for m in motifs
    )


def test_valeur_illisible_declenche_pour_total_ht() -> None:
    bl = _bl_valide(total_ht=None, illisibles=frozenset({"total_ht"}))

    motifs = _verifier(bl)

    assert (
        Motif(
            code=CodeMotif.VALEUR_ILLISIBLE,
            champ="total_ht",
            detail={"champ": "total_ht"},
        )
        in motifs
    )
    assert CodeMotif.TOTAL_ABSENT not in _codes(motifs)


def test_valeur_illisible_ne_declenche_pas_si_convertible() -> None:
    motifs = _verifier(_bl_valide())

    assert CodeMotif.VALEUR_ILLISIBLE not in _codes(motifs)


def test_valeur_illisible_ne_declenche_pas_pour_total_ht_avec_symbole_euro() -> None:
    """L3-T6b, fix round 1 (constat 11, gap confirmé par le contrôleur) :
    un bon d'enlèvement réel a renvoyé `total_ht` sous la forme
    « <montant> € » — `nombre_bl` (bl.py) doit maintenant le convertir, donc
    plus de `VALEUR_ILLISIBLE` sur `total_ht` en bout de chaîne complète
    `analyser_bl` -> `bl_a_verifier` -> `verifier_bl`. Donnée inventée."""
    annotation: dict[str, Any] = {
        "fournisseur": "FOURNISSEUR INVENTE",
        "numero": "BL0001",
        "date_doc": "15/01/2026",
        "chantier_brut": "CHANTIER INVENTE",
        "total_ht": "45,70 €",
        "lignes": [],
    }
    extrait = analyser_bl({"document_annotation": annotation})

    motifs = verifier_bl(
        bl_a_verifier(extrait),
        seuil_confiance=SEUIL_CONFIANCE_DEFAUT,
        tolerance=TOLERANCE_TOTAL_DEFAUT,
    )

    assert not any(
        m.code is CodeMotif.VALEUR_ILLISIBLE and m.champ == "total_ht" for m in motifs
    )


# --------------------------------------------------------------------------
# CONFIANCE_FAIBLE
# --------------------------------------------------------------------------


def test_confiance_faible_declenche_sous_le_seuil() -> None:
    bl = _bl_valide(confiances=_confiances(fournisseur=Decimal("0.50")))

    motifs = _verifier(bl)

    assert (
        Motif(
            code=CodeMotif.CONFIANCE_FAIBLE,
            champ="fournisseur",
            detail={"confiance": "0.50", "seuil": "0.80"},
        )
        in motifs
    )


def test_confiance_faible_ne_declenche_pas_au_dessus_du_seuil() -> None:
    motifs = _verifier(_bl_valide())

    assert CodeMotif.CONFIANCE_FAIBLE not in _codes(motifs)


def test_confiance_faible_seuil_exact_aucun_motif() -> None:
    bl = _bl_valide(confiances=_confiances(fournisseur=Decimal("0.80")))

    motifs = verifier_bl(
        bl, seuil_confiance=Decimal("0.80"), tolerance=TOLERANCE_TOTAL_DEFAUT
    )

    assert CodeMotif.CONFIANCE_FAIBLE not in _codes(motifs)


def test_confiance_faible_juste_sous_le_seuil_declenche() -> None:
    bl = _bl_valide(confiances=_confiances(fournisseur=Decimal("0.7999")))

    motifs = verifier_bl(
        bl, seuil_confiance=Decimal("0.80"), tolerance=TOLERANCE_TOTAL_DEFAUT
    )

    assert CodeMotif.CONFIANCE_FAIBLE in _codes(motifs)


def test_confiance_none_donne_detail_inconnue() -> None:
    bl = _bl_valide(confiances=_confiances(fournisseur=None))

    motifs = _verifier(bl)

    motif = next(m for m in motifs if m.champ == "fournisseur")
    assert motif.detail["confiance"] == "inconnue"


def test_confiances_none_aucun_confiance_faible() -> None:
    bl = _bl_valide(confiances=None)

    motifs = _verifier(bl)

    assert CodeMotif.CONFIANCE_FAIBLE not in _codes(motifs)


def test_confiance_faible_declenche_pour_une_ligne() -> None:
    ligne = LigneAVerifier(
        ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.10")
    )
    bl = _bl_valide(lignes=(ligne,), total_ht=Decimal("10.00"))

    motifs = _verifier(bl)

    assert (
        Motif(
            code=CodeMotif.CONFIANCE_FAIBLE,
            champ="ligne:0",
            detail={"confiance": "0.10", "seuil": "0.80"},
        )
        in motifs
    )


def test_confiance_faible_ne_declenche_pas_pour_une_ligne_bien_lue() -> None:
    ligne = LigneAVerifier(
        ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.99")
    )
    bl = _bl_valide(lignes=(ligne,), total_ht=Decimal("10.00"))

    motifs = _verifier(bl)

    assert not any(m.champ == "ligne:0" for m in motifs)


# --------------------------------------------------------------------------
# SOMME_INCOHERENTE
# --------------------------------------------------------------------------


def test_somme_incoherente_declenche_hors_tolerance() -> None:
    ligne = LigneAVerifier(
        ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.95")
    )
    bl = _bl_valide(lignes=(ligne,), total_ht=Decimal("10.06"))

    motifs = _verifier(bl)

    motif = next(m for m in motifs if m.code is CodeMotif.SOMME_INCOHERENTE)
    assert motif.champ == "total_ht"
    assert motif.detail == {
        "somme": "10.00",
        "total": "10.06",
        "ecart": "-0.06",
        "tolerance": "0.05",
    }


def test_somme_incoherente_ne_declenche_pas_dans_la_tolerance() -> None:
    ligne = LigneAVerifier(
        ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.95")
    )
    bl = _bl_valide(lignes=(ligne,), total_ht=Decimal("10.05"))

    motifs = _verifier(bl)

    assert CodeMotif.SOMME_INCOHERENTE not in _codes(motifs)


def test_somme_incoherente_tolerance_exacte_incluse() -> None:
    """Écart exactement égal à la tolérance : accepté (`<=`, décision de
    la fiche)."""
    ligne = LigneAVerifier(
        ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.95")
    )
    bl = _bl_valide(lignes=(ligne,), total_ht=Decimal("10.05"))

    motifs = verifier_bl(
        bl, seuil_confiance=SEUIL_CONFIANCE_DEFAUT, tolerance=Decimal("0.05")
    )

    assert CodeMotif.SOMME_INCOHERENTE not in _codes(motifs)


def test_somme_incoherente_tolerance_depassee_de_un_centime() -> None:
    ligne = LigneAVerifier(
        ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.95")
    )
    bl = _bl_valide(lignes=(ligne,), total_ht=Decimal("10.06"))

    motifs = verifier_bl(
        bl, seuil_confiance=SEUIL_CONFIANCE_DEFAUT, tolerance=Decimal("0.05")
    )

    assert CodeMotif.SOMME_INCOHERENTE in _codes(motifs)


def test_somme_incoherente_aucune_ligne_et_total_present() -> None:
    bl = _bl_valide(lignes=(), total_ht=Decimal("50.00"))

    motifs = _verifier(bl)

    motif = next(m for m in motifs if m.code is CodeMotif.SOMME_INCOHERENTE)
    assert motif.detail["somme"] == "0"
    assert motif.detail["total"] == "50.00"


def test_ligne_sans_montant_ignoree_dans_la_somme() -> None:
    lignes = (
        LigneAVerifier(ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.95")),
        LigneAVerifier(ordre=1, montant_ht=None, confiance=Decimal("0.95")),
    )
    bl = _bl_valide(lignes=lignes, total_ht=Decimal("10.00"))

    motifs = _verifier(bl)

    assert CodeMotif.SOMME_INCOHERENTE not in _codes(motifs)


# --------------------------------------------------------------------------
# TOTAL_ABSENT (L3-D25, constat 11 : toujours posé si `total_ht` est absent
# et lisible, qu'il y ait ou non des lignes/montants — un document mal cadré
# ne doit jamais paraître silencieusement cohérent).
# --------------------------------------------------------------------------


def test_total_absent_declenche_si_une_ligne_a_un_montant() -> None:
    ligne = LigneAVerifier(
        ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.95")
    )
    bl = _bl_valide(lignes=(ligne,), total_ht=None)

    motifs = _verifier(bl)

    assert (
        Motif(code=CodeMotif.TOTAL_ABSENT, champ="total_ht", detail={"somme": "10.00"})
        in motifs
    )


def test_total_absent_declenche_meme_sans_aucune_ligne() -> None:
    """L3-D25 : plus de condition « au moins une ligne a un montant » — un
    total absent part toujours `TOTAL_ABSENT` (sauf s'il est illisible)."""
    motifs = _verifier(_bl_valide(lignes=(), total_ht=None))

    assert (
        Motif(code=CodeMotif.TOTAL_ABSENT, champ="total_ht", detail={"somme": "0"})
        in motifs
    )


def test_total_absent_declenche_meme_si_aucune_ligne_n_a_de_montant() -> None:
    ligne = LigneAVerifier(ordre=0, montant_ht=None, confiance=Decimal("0.95"))
    bl = _bl_valide(lignes=(ligne,), total_ht=None)

    motifs = _verifier(bl)

    assert CodeMotif.TOTAL_ABSENT in _codes(motifs)


def test_total_absent_ne_declenche_pas_si_total_present() -> None:
    ligne = LigneAVerifier(
        ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.95")
    )
    motifs = _verifier(_bl_valide(lignes=(ligne,), total_ht=Decimal("10.00")))

    assert CodeMotif.TOTAL_ABSENT not in _codes(motifs)


def test_total_absent_ne_declenche_pas_si_illisible() -> None:
    """`VALEUR_ILLISIBLE` couvre déjà ce cas (règle 1) : pas de doublon."""
    bl = _bl_valide(total_ht=None, illisibles=frozenset({"total_ht"}))

    motifs = _verifier(bl)

    assert CodeMotif.TOTAL_ABSENT not in _codes(motifs)


# --------------------------------------------------------------------------
# LIGNES_ABSENTES (L3-D25, constat 11 : la photo mal cadrée n'a produit ni
# tableau ni ligne — posé indépendamment de TOTAL_ABSENT/SOMME_INCOHERENTE).
# --------------------------------------------------------------------------


def test_lignes_absentes_declenche_sans_aucune_ligne() -> None:
    motifs = _verifier(_bl_valide(lignes=(), total_ht=None))

    assert (
        Motif(code=CodeMotif.LIGNES_ABSENTES, champ="lignes", detail={"nb_lignes": "0"})
        in motifs
    )


def test_lignes_absentes_ne_declenche_pas_si_une_ligne_existe() -> None:
    ligne = LigneAVerifier(
        ordre=0, montant_ht=Decimal("10.00"), confiance=Decimal("0.95")
    )
    motifs = _verifier(_bl_valide(lignes=(ligne,), total_ht=Decimal("10.00")))

    assert CodeMotif.LIGNES_ABSENTES not in _codes(motifs)


# --------------------------------------------------------------------------
# NUMERO_INCOHERENT
# --------------------------------------------------------------------------


def test_numero_incoherent_declenche_si_different() -> None:
    bl = _bl_valide(numero="BL0001", numero_detecte="BL0002")

    motifs = _verifier(bl)

    assert (
        Motif(
            code=CodeMotif.NUMERO_INCOHERENT,
            champ="numero",
            detail={"lu": "BL0001", "detecte": "BL0002"},
        )
        in motifs
    )


def test_numero_incoherent_ne_declenche_pas_si_identique() -> None:
    motifs = _verifier(_bl_valide(numero="BL0001", numero_detecte="BL0001"))

    assert CodeMotif.NUMERO_INCOHERENT not in _codes(motifs)


def test_numero_incoherent_normalise_avant_comparaison() -> None:
    """Deux formes brutes différentes mais normalisées identiques (espace,
    casse) ne déclenchent pas le motif — la comparaison passe par
    `normaliser_numero_bl`, pas une égalité de chaîne brute."""
    motifs = _verifier(_bl_valide(numero="bl 0001", numero_detecte="BL0001"))

    assert CodeMotif.NUMERO_INCOHERENT not in _codes(motifs)


def test_numero_incoherent_ne_declenche_pas_si_numero_detecte_absent() -> None:
    motifs = _verifier(_bl_valide(numero="BL0001", numero_detecte=None))

    assert CodeMotif.NUMERO_INCOHERENT not in _codes(motifs)


# --------------------------------------------------------------------------
# bl_a_verifier
# --------------------------------------------------------------------------


def _texte(brut: str | None, confiance: Decimal | None = Decimal("0.9")) -> TexteLu:
    return TexteLu(brut=brut, confiance=confiance)


def _bl_extrait_minimal(**overrides: Any) -> BLExtrait:
    base: dict[str, Any] = {
        "type_bon": _texte(None),
        "fournisseur": _texte("FOURNISSEUR INVENTE"),
        "agence_fournisseur": _texte(None),
        "siret": _texte(None),
        "tva_intracommunautaire": _texte(None),
        "numero": _texte("BL0001"),
        "date_doc": DateLue(
            brut="15/01/2026", valeur=date(2026, 1, 15), confiance=Decimal("0.9")
        ),
        "chantier_brut": _texte("CHANTIER INVENTE"),
        "numero_commande": _texte(None),
        "enleve_par": _texte(None),
        "total_ht": NombreLu(brut=None, valeur=None, confiance=None),
        "total_tva": NombreLu(brut=None, valeur=None, confiance=None),
        "total_ttc": NombreLu(brut=None, valeur=None, confiance=None),
        "lignes": (),
        "numero_detecte": NumeroBL(numero="BL0001", type_bl=TypeBL.LIVRAISON),
    }
    base.update(overrides)
    return BLExtrait(**base)


def test_bl_a_verifier_copie_les_valeurs_converties() -> None:
    extrait = _bl_extrait_minimal()

    bl = bl_a_verifier(extrait)

    assert bl.fournisseur == "FOURNISSEUR INVENTE"
    assert bl.chantier_brut == "CHANTIER INVENTE"
    assert bl.date_doc == date(2026, 1, 15)
    assert bl.numero == "BL0001"
    assert bl.numero_detecte == "BL0001"


def test_bl_a_verifier_illisible_si_brut_present_valeur_none() -> None:
    extrait = _bl_extrait_minimal(
        date_doc=DateLue(brut="pas une date", valeur=None, confiance=Decimal("0.9"))
    )

    bl = bl_a_verifier(extrait)

    assert bl.illisibles == frozenset({"date_doc"})
    assert bl.date_doc is None


def test_bl_a_verifier_absent_ne_compte_pas_comme_illisible() -> None:
    extrait = _bl_extrait_minimal(
        date_doc=DateLue(brut=None, valeur=None, confiance=None)
    )

    bl = bl_a_verifier(extrait)

    assert bl.illisibles == frozenset()


def test_bl_a_verifier_confiances_cles_attendues() -> None:
    extrait = _bl_extrait_minimal()

    bl = bl_a_verifier(extrait)

    assert bl.confiances is not None
    assert set(bl.confiances) == {
        "fournisseur",
        "numero",
        "date_doc",
        "chantier_brut",
        "total_ht",
    }


def test_bl_a_verifier_numero_detecte_none_si_absent() -> None:
    extrait = _bl_extrait_minimal(numero_detecte=None)

    bl = bl_a_verifier(extrait)

    assert bl.numero_detecte is None


def test_bl_a_verifier_confiance_ligne_minimum_des_trois_champs() -> None:
    ligne = LigneBL(
        ordre=0,
        code=_texte("AB1234", Decimal("0.9")),
        designation=_texte("DESIGNATION", Decimal("0.1")),  # ignorée
        quantite_conditionnements=NombreLu(
            brut="4", valeur=Decimal("4"), confiance=Decimal("0.05")
        ),  # ignorée (L3-D24/L3-T6b : n'entre pas dans la confiance de ligne)
        quantite=NombreLu(brut="4", valeur=Decimal("4"), confiance=Decimal("0.5")),
        unite=_texte("U", Decimal("0.1")),  # ignorée
        pu_ht=NombreLu(
            brut="10", valeur=Decimal("10"), confiance=Decimal("0.1")
        ),  # ignorée
        montant_ht=NombreLu(brut="40", valeur=Decimal("40"), confiance=Decimal("0.7")),
    )
    extrait = _bl_extrait_minimal(lignes=(ligne,))

    bl = bl_a_verifier(extrait)

    assert bl.lignes[0].confiance == Decimal("0.5")


def test_bl_a_verifier_confiance_ligne_none_si_les_trois_sont_nulles() -> None:
    ligne = LigneBL(
        ordre=0,
        code=_texte("AB1234", None),
        designation=_texte("DESIGNATION", None),
        quantite_conditionnements=NombreLu(brut=None, valeur=None, confiance=None),
        quantite=NombreLu(brut="4", valeur=Decimal("4"), confiance=None),
        unite=_texte("U", None),
        pu_ht=NombreLu(brut="10", valeur=Decimal("10"), confiance=None),
        montant_ht=NombreLu(brut="40", valeur=Decimal("40"), confiance=None),
    )
    extrait = _bl_extrait_minimal(lignes=(ligne,))

    bl = bl_a_verifier(extrait)

    assert bl.lignes[0].confiance is None


def test_bl_a_verifier_bl_synthetique_verifier_bl_sans_motif() -> None:
    """Intégration : l'annotation synthétique (constat 3, `bl_synthetique.
    mistral-ocr.json`) est cohérente de bout en bout et ne doit déclencher
    aucun motif avec les seuils par défaut."""
    reponse: dict[str, Any] = json.loads(
        (_DONNEES / "bl_synthetique.mistral-ocr.json").read_text(encoding="utf-8")
    )
    extrait = analyser_bl(reponse)

    bl = bl_a_verifier(extrait)
    motifs = verifier_bl(
        bl, seuil_confiance=SEUIL_CONFIANCE_DEFAUT, tolerance=TOLERANCE_TOTAL_DEFAUT
    )

    assert motifs == ()


# --------------------------------------------------------------------------
# verifier_facture
# --------------------------------------------------------------------------


def test_verifier_facture_coherente_aucun_motif() -> None:
    facture = _facture(Decimal("30.00"), Decimal("10.00"), Decimal("20.00"))

    assert verifier_facture(facture, tolerance=TOLERANCE_TOTAL_DEFAUT) == ()


def test_verifier_facture_incoherente_un_motif() -> None:
    facture = _facture(Decimal("30.50"), Decimal("10.00"), Decimal("20.00"))

    motifs = verifier_facture(facture, tolerance=TOLERANCE_TOTAL_DEFAUT)

    assert motifs == (
        Motif(
            code=CodeMotif.SOMME_INCOHERENTE,
            champ="total_ht",
            detail={
                "somme": "30.00",
                "total": "30.50",
                "ecart": "-0.50",
                "tolerance": "0.05",
            },
        ),
    )


def test_verifier_facture_tolerance_exacte_aucun_motif() -> None:
    facture = _facture(Decimal("30.05"), Decimal("10.00"), Decimal("20.00"))

    assert verifier_facture(facture, tolerance=Decimal("0.05")) == ()


# --------------------------------------------------------------------------
# motif_en_json / motif_depuis_json
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", list(CodeMotif))
def test_motif_json_aller_retour(code: CodeMotif) -> None:
    motif = Motif(code=code, champ="numero", detail={"a": "1", "b": "2"})

    assert motif_depuis_json(motif_en_json(motif)) == motif


def test_motif_json_aller_retour_champ_none() -> None:
    motif = Motif(code=CodeMotif.OCR_ECHEC, champ=None, detail={})

    assert motif_depuis_json(motif_en_json(motif)) == motif


def test_motif_en_json_serialisable() -> None:
    motif = Motif(
        code=CodeMotif.SOMME_INCOHERENTE,
        champ="total_ht",
        detail={
            "somme": "1.00",
            "total": "2.00",
            "ecart": "-1.00",
            "tolerance": "0.05",
        },
    )

    resultat = motif_en_json(motif)
    json.dumps(resultat)  # ne doit jamais lever

    assert resultat == {
        "code": "somme_incoherente",
        "champ": "total_ht",
        "detail": {
            "somme": "1.00",
            "total": "2.00",
            "ecart": "-1.00",
            "tolerance": "0.05",
        },
    }


def test_motif_depuis_json_code_inconnu_leve() -> None:
    with pytest.raises(ValueError, match="code"):
        motif_depuis_json(
            {"code": "code_qui_n_existe_pas", "champ": None, "detail": {}}
        )


def test_motif_depuis_json_code_absent_leve() -> None:
    with pytest.raises(ValueError):
        motif_depuis_json({"champ": None, "detail": {}})


def test_motif_depuis_json_detail_mal_forme_leve() -> None:
    with pytest.raises(ValueError):
        motif_depuis_json({"code": "champ_absent", "champ": None, "detail": {"a": 1}})


def test_motif_depuis_json_champ_mal_forme_leve() -> None:
    with pytest.raises(ValueError):
        motif_depuis_json({"code": "champ_absent", "champ": 123, "detail": {}})


@pytest.mark.parametrize("donnees", [None, ["a"], "x"])
def test_motif_depuis_json_donnees_non_objet_leve_value_error(donnees: Any) -> None:
    """`donnees` non indexable par clé (`None`, une liste, une chaîne) doit
    lever `ValueError`, jamais le `TypeError` natif de l'indexation
    (`donnees["code"]`) — contrat documenté de la fonction."""
    with pytest.raises(ValueError):
        motif_depuis_json(donnees)


def test_motif_depuis_json_detail_non_dict_leve() -> None:
    with pytest.raises(ValueError):
        motif_depuis_json({"code": "champ_absent", "champ": None, "detail": ["a"]})


def test_motif_depuis_json_detail_cle_non_chaine_leve() -> None:
    with pytest.raises(ValueError):
        motif_depuis_json({"code": "champ_absent", "champ": None, "detail": {1: "a"}})


# --------------------------------------------------------------------------
# Fixture réelle (skip si absente dans cet arbre de travail, décision du
# contrôleur) : aucune valeur affichée, seulement une égalité.
# --------------------------------------------------------------------------

_CHEMIN_FACTURE_REELLE = (
    Path(__file__).resolve().parents[4]
    / "tests"
    / "fixtures"
    / "unikalo"
    / "facture_2026-08.mistral-ocr.json"
)


def test_verifier_facture_fixture_reelle_sans_motif() -> None:
    if not _CHEMIN_FACTURE_REELLE.exists():
        pytest.skip(
            "fixture réelle absente dans cet arbre de travail "
            "(tests/fixtures/ ignoré par git, déposée après intégration)"
        )
    reponse: dict[str, Any] = json.loads(
        _CHEMIN_FACTURE_REELLE.read_text(encoding="utf-8")
    )
    facture = analyser_facture_unikalo(reponse)

    # Ruling R7 : on ne compare jamais directement au tuple de motifs — un
    # échec ferait apparaître, via l'assertion réécrite par pytest, le
    # `detail` du `Motif` (somme/total/écart réels du document client).
    # On ne compare qu'un booléen, avec un message fixe sans valeur.
    sans_motif = len(verifier_facture(facture, tolerance=TOLERANCE_TOTAL_DEFAUT)) == 0
    assert sans_motif, "la facture réelle ne doit produire aucun motif"


# --------------------------------------------------------------------------
# Fixtures réelles de BL (L3-T6b, constat 11, décision du contrôleur) :
# `tests/fixtures/bl/*.mistral-ocr.json`, produites avec l'ancien schéma
# d'annotation (avant `quantite_conditionnements`) — la mesure du taux
# d'erreur se fait avec L3-T11 (`rapport-ocr`). Ici on vérifie seulement que
# `analyser_bl` puis `verifier_bl` ne lèvent jamais sur ces réponses réelles,
# jamais une valeur (Ruling R7 : booléen affirmé avec un message fixe).
# --------------------------------------------------------------------------

_DOSSIER_BL_REEL = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "bl"


def test_bl_a_verifier_fixtures_reelles_sans_lever() -> None:
    fichiers = (
        sorted(_DOSSIER_BL_REEL.glob("*.mistral-ocr.json"))
        if _DOSSIER_BL_REEL.exists()
        else []
    )
    if not fichiers:
        pytest.skip(
            "fixtures réelles absentes dans cet arbre de travail "
            "(tests/fixtures/ ignoré par git)"
        )

    ok = True
    for fichier in fichiers:
        reponse: dict[str, Any] = json.loads(fichier.read_text(encoding="utf-8"))
        try:
            verifier_bl(
                bl_a_verifier(analyser_bl(reponse)),
                seuil_confiance=SEUIL_CONFIANCE_DEFAUT,
                tolerance=TOLERANCE_TOTAL_DEFAUT,
            )
        except AnnotationIllisible:
            pass
        except Exception:
            ok = False
    assert ok, "l'analyse d'une réponse OCR réelle ne doit pas lever"


# --------------------------------------------------------------------------
# retirer_motifs_confirmes (lot 2 du 31/10/2026, A2)
# --------------------------------------------------------------------------


def _motif_test(code: CodeMotif, champ: str | None) -> Motif:
    return Motif(code=code, champ=champ, detail={"champ": champ or ""})


def test_retirer_motifs_confirmes_retire_la_confiance_faible_du_champ_confirme() -> (
    None
):
    from app.modules.extract.verification import retirer_motifs_confirmes

    motifs = (
        _motif_test(CodeMotif.CONFIANCE_FAIBLE, "fournisseur"),
        _motif_test(CodeMotif.CONFIANCE_FAIBLE, "numero"),
    )

    reste = retirer_motifs_confirmes(motifs, frozenset({"fournisseur"}))

    assert reste == (motifs[1],)


def test_retirer_motifs_confirmes_ne_touche_pas_aux_autres_codes_du_champ() -> None:
    from app.modules.extract.verification import retirer_motifs_confirmes

    motifs = (
        _motif_test(CodeMotif.CHAMP_ABSENT, "fournisseur"),
        _motif_test(CodeMotif.FOURNISSEUR_INCONNU, "fournisseur"),
        _motif_test(CodeMotif.VALEUR_ILLISIBLE, "fournisseur"),
    )

    assert retirer_motifs_confirmes(motifs, frozenset({"fournisseur"})) == motifs


def test_retirer_motifs_confirmes_sans_champ_confirme_ne_change_rien() -> None:
    from app.modules.extract.verification import retirer_motifs_confirmes

    motifs = (_motif_test(CodeMotif.CONFIANCE_FAIBLE, "fournisseur"),)

    assert retirer_motifs_confirmes(motifs, frozenset()) == motifs
    assert retirer_motifs_confirmes((), frozenset({"fournisseur"})) == ()
