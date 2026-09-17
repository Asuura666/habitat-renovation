"""Tests de `rapport_ocr.py` (L3-T11, L3-D20).

Comme `test_bl.py`/`test_extraction_bl.py`, toutes les données sont
inventées : `comparer_bl`/`agreger`/`lire_attendu`/`rapport_markdown` sont
testés sur des dataclasses construites à la main (aucun besoin d'une
réponse OCR complète) ; `mesurer_dossier` (E/S disque, `tmp_path`) relit la
réponse OCR synthétique `app/modules/extract/tests/donnees/
bl_synthetique.mistral-ocr.json` (constat 3 du plan lot 3, même mécanique
que `test_extraction_bl.py`) comme contenu de cache ou de réponse OCR
factice — jamais un second fichier fixture. Aucune fixture réelle
(`tests/fixtures/`) n'est utilisée ici, et l'outil n'est jamais lancé sur
les photos réelles ni sur un appel Mistral réel (décision du contrôleur,
R17)."""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.extract.bl import (
    BLExtrait,
    DateLue,
    LigneBL,
    NombreLu,
    TexteLu,
)
from app.modules.extract.ocr import NumeroBL, TypeBL
from app.modules.extract.verification import (
    SEUIL_CONFIANCE_DEFAUT,
    TOLERANCE_TOTAL_DEFAUT,
    CodeMotif,
)
from app.modules.ingest.rapport_ocr import (
    BLAttendu,
    ChampCompare,
    ComparaisonBL,
    LigneAttendue,
    LigneComparee,
    agreger,
    comparer_bl,
    lire_attendu,
    mesurer_dossier,
    rapport_markdown,
)

pytestmark = pytest.mark.anyio

_DONNEES_SYNTHETIQUES = (
    Path(__file__).resolve().parent.parent.parent
    / "extract"
    / "tests"
    / "donnees"
    / "bl_synthetique.mistral-ocr.json"
)
with _DONNEES_SYNTHETIQUES.open(encoding="utf-8") as _fichier:
    _REPONSE_SYNTHETIQUE_BASE: dict[str, Any] = json.load(_fichier)


def _reponse_synthetique() -> dict[str, Any]:
    """Copie profonde de la donnée synthétique (jamais mutée en place, jamais
    relue depuis le disque plusieurs fois)."""
    return copy.deepcopy(_REPONSE_SYNTHETIQUE_BASE)


def _attendu_bl_synthetique() -> dict[str, Any]:
    """`<nom>.attendu.json` inventé correspondant exactement au BL
    synthétique (constat 3 : fournisseur, BL, chantier et articles
    entièrement inventés)."""
    return {
        "numero": "L209900000123",
        "fournisseur": "Peintures Exemple",
        "date_doc": "2026-09-03",
        "chantier_brut": "MAISON TEST (9900000001)",
        "degradee": False,
        "lignes": [
            {"code": "AB1234", "quantite": "4"},
            {"code": "CD5678", "quantite": "2"},
            {"code": "EF9012", "quantite": "10"},
        ],
    }


# --------------------------------------------------------------------------
# Constructeurs de données inventées (comparer_bl)
# --------------------------------------------------------------------------


def _texte(brut: str | None, confiance: Decimal | None) -> TexteLu:
    return TexteLu(brut=brut, confiance=confiance)


def _ligne_bl(
    code: str | None,
    quantite: Decimal | None,
    montant_ht: Decimal | None,
    *,
    confiance: Decimal | None = Decimal("0.99"),
    ordre: int = 0,
) -> LigneBL:
    return LigneBL(
        ordre=ordre,
        code=_texte(code, confiance if code is not None else None),
        designation=_texte("DESIGNATION INVENTEE", confiance),
        quantite_conditionnements=NombreLu(brut=None, valeur=None, confiance=None),
        quantite=NombreLu(
            brut=str(quantite) if quantite is not None else None,
            valeur=quantite,
            confiance=confiance if quantite is not None else None,
        ),
        unite=_texte("U", confiance),
        pu_ht=NombreLu(brut=None, valeur=None, confiance=None),
        montant_ht=NombreLu(
            brut=str(montant_ht) if montant_ht is not None else None,
            valeur=montant_ht,
            confiance=confiance if montant_ht is not None else None,
        ),
    )


_LIGNE_JUSTE = _ligne_bl("AB1234", Decimal("4"), Decimal("40.00"))


def _extrait(
    *,
    numero: str | None = "BL0001",
    fournisseur: str | None = "FOURNISSEUR INVENTE",
    date_doc: date | None = date(2026, 1, 15),
    chantier_brut: str | None = "CHANTIER INVENTE",
    total_ht: Decimal | None = Decimal("40.00"),
    lignes: tuple[LigneBL, ...] = (_LIGNE_JUSTE,),
    confiance_entete: Decimal | None = Decimal("0.99"),
    numero_detecte: NumeroBL | None = None,
) -> BLExtrait:
    """`BLExtrait` inventé, toutes les confiances au-dessus du seuil par
    défaut, qui ne déclenche aucun motif de `verifier_bl` (base des tests
    de `comparer_bl`, chaque test override seulement ce qui l'intéresse)."""
    return BLExtrait(
        type_bon=_texte("livraison", confiance_entete),
        fournisseur=_texte(fournisseur, confiance_entete if fournisseur else None),
        agence_fournisseur=_texte(None, None),
        siret=_texte(None, None),
        tva_intracommunautaire=_texte(None, None),
        numero=_texte(numero, confiance_entete if numero else None),
        date_doc=DateLue(
            brut=date_doc.isoformat() if date_doc else None,
            valeur=date_doc,
            confiance=confiance_entete if date_doc else None,
        ),
        chantier_brut=_texte(
            chantier_brut, confiance_entete if chantier_brut else None
        ),
        numero_commande=_texte(None, None),
        enleve_par=_texte(None, None),
        total_ht=NombreLu(
            brut=str(total_ht) if total_ht is not None else None,
            valeur=total_ht,
            confiance=confiance_entete if total_ht is not None else None,
        ),
        total_tva=NombreLu(brut=None, valeur=None, confiance=None),
        total_ttc=NombreLu(brut=None, valeur=None, confiance=None),
        lignes=lignes,
        numero_detecte=numero_detecte,
    )


def _attendu(
    *,
    nom: str = "photo-test",
    numero: str = "BL0001",
    fournisseur: str = "Fournisseur Invente",
    date_doc: date = date(2026, 1, 15),
    chantier_brut: str = "Chantier Invente",
    lignes: tuple[LigneAttendue, ...] = (
        LigneAttendue(code="AB1234", quantite=Decimal("4")),
    ),
    degradee: bool = False,
) -> BLAttendu:
    return BLAttendu(
        nom=nom,
        numero=numero,
        fournisseur=fournisseur,
        date_doc=date_doc,
        chantier_brut=chantier_brut,
        lignes=lignes,
        degradee=degradee,
    )


def _comparer(extrait: BLExtrait, attendu: BLAttendu) -> ComparaisonBL:
    return comparer_bl(
        extrait, attendu, seuil=SEUIL_CONFIANCE_DEFAUT, tolerance=TOLERANCE_TOTAL_DEFAUT
    )


# --------------------------------------------------------------------------
# comparer_bl — tout juste
# --------------------------------------------------------------------------


def test_comparer_bl_tout_juste_aucun_motif_non_silencieuse() -> None:
    comparaison = _comparer(_extrait(), _attendu())

    assert all(c.juste for c in comparaison.champs)
    assert all(ligne.juste for ligne in comparaison.lignes)
    assert comparaison.lignes_en_trop == 0
    assert comparaison.motifs == ()
    assert comparaison.silencieuse is False
    assert comparaison.nom == "photo-test"
    assert comparaison.degradee is False


# --------------------------------------------------------------------------
# comparer_bl — numéro faux avec motif -> non silencieuse
# --------------------------------------------------------------------------


def test_comparer_bl_numero_faux_avec_motif_non_silencieuse() -> None:
    """Numéro annoté incohérent avec le motif déterministe existant
    (`detecter_numero_bl`) : `NUMERO_INCOHERENT` est posé, la comparaison
    n'est donc jamais silencieuse malgré le champ faux."""
    extrait = _extrait(
        numero="BL9999",
        numero_detecte=NumeroBL(numero="BL0001", type_bl=TypeBL.LIVRAISON),
    )

    comparaison = _comparer(extrait, _attendu())

    champ_numero = next(c for c in comparaison.champs if c.champ == "numero")
    assert champ_numero.juste is False
    assert CodeMotif.NUMERO_INCOHERENT.value in comparaison.motifs
    assert comparaison.silencieuse is False


# --------------------------------------------------------------------------
# comparer_bl — chantier faux sans motif -> silencieuse
# --------------------------------------------------------------------------


def test_comparer_bl_chantier_faux_sans_motif_silencieuse() -> None:
    extrait = _extrait(chantier_brut="AUTRE CHANTIER INVENTE")

    comparaison = _comparer(extrait, _attendu())

    champ_chantier = next(c for c in comparaison.champs if c.champ == "chantier_brut")
    assert champ_chantier.juste is False
    assert comparaison.motifs == ()
    assert comparaison.silencieuse is True


# --------------------------------------------------------------------------
# comparer_bl — fournisseur : mots de l'attendu inclus dans le lu
# --------------------------------------------------------------------------


def test_comparer_bl_fournisseur_juste_si_mots_attendu_inclus_dans_lu() -> None:
    extrait = _extrait(fournisseur="PEINTURES EXEMPLE SAS AGENCE NORD")

    comparaison = _comparer(extrait, _attendu(fournisseur="Peintures Exemple"))

    champ_fournisseur = next(c for c in comparaison.champs if c.champ == "fournisseur")
    assert champ_fournisseur.juste is True


def test_comparer_bl_fournisseur_faux_si_mot_attendu_absent_du_lu() -> None:
    extrait = _extrait(fournisseur="PEINTURES EXEMPLE")

    comparaison = _comparer(extrait, _attendu(fournisseur="Peintures Exemple SAS"))

    champ_fournisseur = next(c for c in comparaison.champs if c.champ == "fournisseur")
    assert champ_fournisseur.juste is False


# --------------------------------------------------------------------------
# comparer_bl — lignes : manquante, quantité fausse à confiance haute, en trop
# --------------------------------------------------------------------------


def test_comparer_bl_ligne_manquante_non_trouvee() -> None:
    attendu = _attendu(
        lignes=(
            LigneAttendue(code="AB1234", quantite=Decimal("4")),
            LigneAttendue(code="CD5678", quantite=Decimal("2")),
        )
    )

    comparaison = _comparer(_extrait(), attendu)

    assert len(comparaison.lignes) == 2
    manquante = next(
        ligne for ligne in comparaison.lignes if ligne.code_attendu == "CD5678"
    )
    assert manquante.trouvee is False
    assert manquante.juste is False
    assert manquante.confiance is None
    assert comparaison.silencieuse is True  # aucun motif : ligne manquante non signalée


def test_comparer_bl_quantite_fausse_confiance_haute_listee() -> None:
    ligne_lue = _ligne_bl(
        "AB1234", Decimal("999"), Decimal("40.00"), confiance=Decimal("0.99")
    )
    extrait = _extrait(lignes=(ligne_lue,))

    comparaison = _comparer(extrait, _attendu())

    ligne_comparee = comparaison.lignes[0]
    assert ligne_comparee.trouvee is True
    assert ligne_comparee.juste is False
    assert ligne_comparee.confiance == Decimal("0.99")

    rapport = agreger([comparaison], [], seuil=SEUIL_CONFIANCE_DEFAUT)
    assert rapport.lignes_fausses_confiance_haute == (
        ("photo-test", "AB1234", Decimal("0.99")),
    )


def test_comparer_bl_ligne_en_trop_comptee() -> None:
    ligne_extra = _ligne_bl("ZZ9999", Decimal("1"), Decimal("5.00"), ordre=1)
    extrait = _extrait(
        lignes=(_LIGNE_JUSTE, ligne_extra),
        total_ht=Decimal("45.00"),
    )
    attendu = _attendu(lignes=(LigneAttendue(code="AB1234", quantite=Decimal("4")),))

    comparaison = _comparer(extrait, attendu)

    assert comparaison.lignes_en_trop == 1
    assert len(comparaison.lignes) == 1
    assert comparaison.lignes[0].juste is True


def test_comparer_bl_ligne_code_null_appariee_a_premiere_ligne_lue_code_absent() -> (
    None
):
    """L3-T11, décision du contrôleur : une ligne attendue `code: null`
    (éco-participation) s'apparie à la première ligne lue non appariée dont
    le code est lui aussi absent."""
    ligne_eco_lue = _ligne_bl(None, Decimal("1"), Decimal("2.00"), ordre=1)
    extrait = _extrait(lignes=(_LIGNE_JUSTE, ligne_eco_lue), total_ht=Decimal("42.00"))
    attendu = _attendu(
        lignes=(
            LigneAttendue(code="AB1234", quantite=Decimal("4")),
            LigneAttendue(code=None, quantite=Decimal("1")),
        )
    )

    comparaison = _comparer(extrait, attendu)

    ligne_eco_comparee = next(
        ligne for ligne in comparaison.lignes if ligne.code_attendu is None
    )
    assert ligne_eco_comparee.trouvee is True
    assert ligne_eco_comparee.juste is True
    assert comparaison.lignes_en_trop == 0


# --------------------------------------------------------------------------
# lire_attendu
# --------------------------------------------------------------------------


def test_lire_attendu_valide() -> None:
    donnees = {
        "numero": "L209900000123",
        "fournisseur": "Peintures Exemple",
        "date_doc": "2026-09-03",
        "chantier_brut": "MAISON TEST (9900000001)",
        "total_ht": "161.50",
        "degradee": True,
        "lignes": [
            {"code": "AB1234", "quantite": "100"},
            {"code": None, "quantite": "10"},
        ],
    }

    attendu = lire_attendu(donnees, "photo-1")

    assert attendu.nom == "photo-1"
    assert attendu.numero == "L209900000123"
    assert attendu.fournisseur == "Peintures Exemple"
    assert attendu.date_doc == date(2026, 9, 3)
    assert attendu.chantier_brut == "MAISON TEST (9900000001)"
    assert attendu.degradee is True
    assert attendu.lignes == (
        LigneAttendue(code="AB1234", quantite=Decimal("100")),
        LigneAttendue(code=None, quantite=Decimal("10")),
    )


def test_lire_attendu_total_ht_facultatif_ignore() -> None:
    donnees = {
        "numero": "BL1",
        "fournisseur": "F",
        "date_doc": "2026-09-03",
        "chantier_brut": "C",
        "degradee": False,
        "lignes": [],
    }

    attendu = lire_attendu(donnees, "photo-2")

    assert attendu.numero == "BL1"
    assert attendu.lignes == ()


def test_lire_attendu_cle_inconnue_jamais_une_erreur() -> None:
    donnees = {
        "numero": "BL1",
        "fournisseur": "F",
        "date_doc": "2026-09-03",
        "chantier_brut": "C",
        "degradee": False,
        "lignes": [],
        "cle_totalement_inconnue": "peu importe",
    }

    attendu = lire_attendu(donnees, "photo-3")

    assert attendu.numero == "BL1"


@pytest.mark.parametrize(
    "donnees",
    [
        {},
        {
            "numero": "BL1",
            "fournisseur": "F",
            "date_doc": "2026-09-03",
            "chantier_brut": "C",
            "degradee": False,
        },  # 'lignes' manquante
        {
            "numero": "",
            "fournisseur": "F",
            "date_doc": "2026-09-03",
            "chantier_brut": "C",
            "degradee": False,
            "lignes": [],
        },  # numero vide
        {
            "numero": "BL1",
            "fournisseur": "F",
            "date_doc": "pas une date",
            "chantier_brut": "C",
            "degradee": False,
            "lignes": [],
        },
        {
            "numero": "BL1",
            "fournisseur": "F",
            "date_doc": "2026-09-03",
            "chantier_brut": "C",
            "degradee": "oui",
            "lignes": [],
        },  # 'degradee' pas un booléen
        {
            "numero": "BL1",
            "fournisseur": "F",
            "date_doc": "2026-09-03",
            "chantier_brut": "C",
            "degradee": False,
            "lignes": "pas une liste",
        },
        {
            "numero": "BL1",
            "fournisseur": "F",
            "date_doc": "2026-09-03",
            "chantier_brut": "C",
            "degradee": False,
            "lignes": [{"code": "A"}],
        },  # 'quantite' manquante
        {
            "numero": "BL1",
            "fournisseur": "F",
            "date_doc": "2026-09-03",
            "chantier_brut": "C",
            "degradee": False,
            "lignes": [{"code": "A", "quantite": "pas un nombre"}],
        },
        [],  # pas un objet
    ],
)
def test_lire_attendu_invalide_leve(donnees: Any) -> None:
    with pytest.raises(ValueError):
        lire_attendu(donnees, "photo-invalide")


# --------------------------------------------------------------------------
# agreger
# --------------------------------------------------------------------------


def test_agreger_taux_champs_documents_et_lignes() -> None:
    comp1 = ComparaisonBL(
        nom="doc1",
        degradee=False,
        champs=(
            ChampCompare("numero", True, Decimal("0.9")),
            ChampCompare("fournisseur", True, Decimal("0.9")),
            ChampCompare("date_doc", True, Decimal("0.9")),
            ChampCompare("chantier_brut", True, Decimal("0.9")),
        ),
        lignes=(LigneComparee("AB1234", True, True, Decimal("0.9")),),
        lignes_en_trop=0,
        motifs=(),
        silencieuse=False,
    )
    comp2 = ComparaisonBL(
        nom="doc2",
        degradee=True,
        champs=(
            ChampCompare("numero", True, Decimal("0.9")),
            ChampCompare("fournisseur", False, Decimal("0.2")),
            ChampCompare("date_doc", True, Decimal("0.9")),
            ChampCompare("chantier_brut", True, Decimal("0.9")),
        ),
        lignes=(LigneComparee("CD5678", False, False, None),),
        lignes_en_trop=0,
        motifs=("champ_absent",),
        silencieuse=False,
    )

    rapport = agreger([comp1, comp2], [], seuil=SEUIL_CONFIANCE_DEFAUT)

    assert rapport.nb_documents == 2
    assert rapport.nb_degrades == 1
    assert rapport.taux_champs["numero"] == Decimal("1")
    assert rapport.taux_champs["fournisseur"] == Decimal("0.5")
    assert rapport.taux_champs["date_doc"] == Decimal("1")
    assert rapport.taux_champs["chantier_brut"] == Decimal("1")
    assert rapport.taux_documents_4_champs == Decimal("0.5")
    assert rapport.taux_lignes == Decimal("0.5")
    assert rapport.nb_erreurs_silencieuses == 0
    assert rapport.confiances_justes == (Decimal("0.9"),) * 8
    assert rapport.confiances_fausses == (Decimal("0.2"),)


def test_agreger_erreurs_silencieuses_comptees() -> None:
    comp_silencieuse = ComparaisonBL(
        nom="doc-silencieux",
        degradee=False,
        champs=(
            ChampCompare("numero", True, None),
            ChampCompare("fournisseur", True, None),
            ChampCompare("date_doc", True, None),
            ChampCompare("chantier_brut", False, None),
        ),
        lignes=(),
        lignes_en_trop=0,
        motifs=(),
        silencieuse=True,
    )

    rapport = agreger([comp_silencieuse], [], seuil=SEUIL_CONFIANCE_DEFAUT)

    assert rapport.nb_erreurs_silencieuses == 1


def test_agreger_lignes_fausses_confiance_haute_filtre_par_seuil() -> None:
    comp = ComparaisonBL(
        nom="doc1",
        degradee=False,
        champs=(
            ChampCompare("numero", True, Decimal("0.9")),
            ChampCompare("fournisseur", True, Decimal("0.9")),
            ChampCompare("date_doc", True, Decimal("0.9")),
            ChampCompare("chantier_brut", True, Decimal("0.9")),
        ),
        lignes=(
            LigneComparee(
                "AB1234", True, False, Decimal("0.85")
            ),  # haute, fausse -> listée
            LigneComparee(
                "CD5678", True, False, Decimal("0.10")
            ),  # basse, fausse -> écartée
            LigneComparee(
                "EF9012", True, True, Decimal("0.99")
            ),  # juste -> jamais listée
        ),
        lignes_en_trop=0,
        motifs=(),
        silencieuse=True,
    )

    rapport = agreger([comp], [], seuil=Decimal("0.80"))

    assert rapport.lignes_fausses_confiance_haute == (
        ("doc1", "AB1234", Decimal("0.85")),
    )


def test_agreger_documents_sans_ocr_passthrough_et_taux_a_zero() -> None:
    rapport = agreger([], ["photo-sans-cache"], seuil=SEUIL_CONFIANCE_DEFAUT)

    assert rapport.nb_documents == 0
    assert rapport.documents_sans_ocr == ("photo-sans-cache",)
    assert rapport.taux_champs == {
        "numero": Decimal("0"),
        "fournisseur": Decimal("0"),
        "date_doc": Decimal("0"),
        "chantier_brut": Decimal("0"),
    }
    assert rapport.taux_documents_4_champs == Decimal("0")
    assert rapport.taux_lignes == Decimal("0")


# --------------------------------------------------------------------------
# rapport_markdown
# --------------------------------------------------------------------------


def test_rapport_markdown_contient_synthese_et_detail() -> None:
    comparaison = _comparer(_extrait(), _attendu())
    rapport = agreger([comparaison], ["photo-manquante"], seuil=SEUIL_CONFIANCE_DEFAUT)

    texte = rapport_markdown(rapport, [comparaison])

    assert "# Rapport" in texte
    assert "photo-test" in texte
    assert "photo-manquante" in texte
    assert "≥ 95 %" in texte
    assert "≥ 90 %" in texte


# --------------------------------------------------------------------------
# mesurer_dossier
# --------------------------------------------------------------------------


async def test_mesurer_dossier_cache_present_ocr_jamais_appele(tmp_path: Path) -> None:
    nom = "photo-cache"
    (tmp_path / f"{nom}.jpg").write_bytes(b"contenu invente")
    (tmp_path / f"{nom}.mistral-ocr.json").write_text(
        json.dumps(_reponse_synthetique()), encoding="utf-8"
    )
    (tmp_path / f"{nom}.attendu.json").write_text(
        json.dumps(_attendu_bl_synthetique()), encoding="utf-8"
    )

    appels: list[tuple[bytes, str]] = []

    async def _ocr_jamais_appele(contenu: bytes, mime: str) -> dict[str, Any]:
        appels.append((contenu, mime))
        raise AssertionError("l'OCR ne doit jamais être appelé quand un cache existe")

    rapport, comparaisons = await mesurer_dossier(
        tmp_path,
        ocr=_ocr_jamais_appele,
        seuil=SEUIL_CONFIANCE_DEFAUT,
        tolerance=TOLERANCE_TOTAL_DEFAUT,
    )

    assert appels == []
    assert rapport.nb_documents == 1
    assert rapport.documents_sans_ocr == ()
    assert comparaisons[0].nom == nom
    assert all(c.juste for c in comparaisons[0].champs)
    assert all(ligne.juste for ligne in comparaisons[0].lignes)


async def test_mesurer_dossier_sans_cache_sans_ocr_liste_document_sans_ocr(
    tmp_path: Path,
) -> None:
    nom = "photo-sans-cache"
    (tmp_path / f"{nom}.jpg").write_bytes(b"contenu invente")
    (tmp_path / f"{nom}.attendu.json").write_text(
        json.dumps(
            {
                "numero": "BL1",
                "fournisseur": "F",
                "date_doc": "2026-01-15",
                "chantier_brut": "C",
                "degradee": False,
                "lignes": [],
            }
        ),
        encoding="utf-8",
    )

    rapport, comparaisons = await mesurer_dossier(
        tmp_path,
        ocr=None,
        seuil=SEUIL_CONFIANCE_DEFAUT,
        tolerance=TOLERANCE_TOTAL_DEFAUT,
    )

    assert rapport.nb_documents == 0
    assert rapport.documents_sans_ocr == (nom,)
    assert comparaisons == []
    assert not (tmp_path / f"{nom}.mistral-ocr.json").exists()


async def test_mesurer_dossier_ocr_factice_appele_et_cache_ecrit(
    tmp_path: Path,
) -> None:
    nom = "photo-a-analyser"
    (tmp_path / f"{nom}.jpg").write_bytes(b"contenu invente")
    (tmp_path / f"{nom}.attendu.json").write_text(
        json.dumps(_attendu_bl_synthetique()), encoding="utf-8"
    )

    appels: list[tuple[bytes, str]] = []

    async def _ocr_factice(contenu: bytes, mime: str) -> dict[str, Any]:
        appels.append((contenu, mime))
        return _reponse_synthetique()

    rapport, comparaisons = await mesurer_dossier(
        tmp_path,
        ocr=_ocr_factice,
        seuil=SEUIL_CONFIANCE_DEFAUT,
        tolerance=TOLERANCE_TOTAL_DEFAUT,
    )

    assert len(appels) == 1
    assert appels[0] == (b"contenu invente", "image/jpeg")
    assert rapport.nb_documents == 1
    assert comparaisons[0].nom == nom

    chemin_cache = tmp_path / f"{nom}.mistral-ocr.json"
    assert chemin_cache.is_file()
    cache_ecrit = json.loads(chemin_cache.read_text(encoding="utf-8"))
    assert (
        cache_ecrit["document_annotation"]
        == _reponse_synthetique()["document_annotation"]
    )


async def test_mesurer_dossier_annotation_illisible_motif_et_non_silencieuse(
    tmp_path: Path,
) -> None:
    nom = "photo-illisible"
    reponse = _reponse_synthetique()
    del reponse["document_annotation"]
    (tmp_path / f"{nom}.jpg").write_bytes(b"contenu invente")
    (tmp_path / f"{nom}.mistral-ocr.json").write_text(
        json.dumps(reponse), encoding="utf-8"
    )
    (tmp_path / f"{nom}.attendu.json").write_text(
        json.dumps(_attendu_bl_synthetique()), encoding="utf-8"
    )

    rapport, comparaisons = await mesurer_dossier(
        tmp_path,
        ocr=None,
        seuil=SEUIL_CONFIANCE_DEFAUT,
        tolerance=TOLERANCE_TOTAL_DEFAUT,
    )

    assert rapport.nb_documents == 1
    comparaison = comparaisons[0]
    assert all(not c.juste for c in comparaison.champs)
    assert all(not ligne.juste for ligne in comparaison.lignes)
    assert comparaison.motifs == (CodeMotif.ANNOTATION_ILLISIBLE.value,)
    assert comparaison.silencieuse is False


async def test_mesurer_dossier_photo_sans_attendu_ignoree(tmp_path: Path) -> None:
    (tmp_path / "sans-attendu.jpg").write_bytes(b"contenu invente")

    rapport, comparaisons = await mesurer_dossier(
        tmp_path,
        ocr=None,
        seuil=SEUIL_CONFIANCE_DEFAUT,
        tolerance=TOLERANCE_TOTAL_DEFAUT,
    )

    assert rapport.nb_documents == 0
    assert rapport.documents_sans_ocr == ()
    assert comparaisons == []


async def test_mesurer_dossier_extension_non_photo_ignoree(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("pas une photo", encoding="utf-8")
    (tmp_path / "notes.attendu.json").write_text(
        json.dumps(
            {
                "numero": "BL1",
                "fournisseur": "F",
                "date_doc": "2026-01-15",
                "chantier_brut": "C",
                "degradee": False,
                "lignes": [],
            }
        ),
        encoding="utf-8",
    )

    rapport, comparaisons = await mesurer_dossier(
        tmp_path,
        ocr=None,
        seuil=SEUIL_CONFIANCE_DEFAUT,
        tolerance=TOLERANCE_TOTAL_DEFAUT,
    )

    assert rapport.nb_documents == 0
    assert rapport.documents_sans_ocr == ()
    assert comparaisons == []
