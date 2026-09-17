"""Tests du parseur de facture Unikalo (`unikalo.py`).

Trois familles de tests, comme l'exige la requalification T5 (+ ruling R19) :

- des tests synthétiques, avec des réponses OCR entièrement inventées dans
  ce fichier (aucune donnée réelle, ils tournent toujours) ;
- des tests génériques sur les vraies fixtures `tests/fixtures/unikalo/
  *.mistral-ocr.json` (`pytest.skip` si aucune n'est présente), qui ne
  comparent que des comptes et des booléens, jamais une valeur de document ;
- des tests de non-régression contre un fichier de référence
  `<nom>.attendu.json` (R19), quand il existe pour une fixture donnée ; les
  messages d'échec ne portent que l'index du bloc et le nom du champ en
  écart, jamais une valeur.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.extract.facture import FactureIllisible, TypeLigne
from app.modules.extract.ocr import texte_ocr
from app.modules.extract.unikalo import analyser_facture_unikalo

# --------------------------------------------------------------------------
# Constructeurs de réponses OCR inventées (aucune donnée réelle)
# --------------------------------------------------------------------------

_ENTETE_COLONNES = (
    "| ARTICLE | DÉSIGNATION | QTÉ LIVRÉE | QTÉ TOTALE | PRIX H.T. "
    "| PRIX CDT REMISE | MONTANT H.T. | TVA |"
)
_SEPARATEUR_COLONNES = "| --- | --- | --- | --- | --- | --- | --- | --- |"


def _ligne(*cellules: str) -> str:
    assert len(cellules) == 8, "une ligne de facture Unikalo a 8 cellules"
    return "| " + " | ".join(cellules) + " |"


def _table(*lignes_donnees: str) -> str:
    return "\n".join([_ENTETE_COLONNES, _SEPARATEUR_COLONNES, *lignes_donnees])


def _recap(total_ht: str, taux_par_code: dict[str, str] | None = None) -> str:
    taux_par_code = {"5": "(20%)"} if taux_par_code is None else taux_par_code
    lignes = ["| H.T. € | Code | Taux | T.V.A. € |", "| --- | --- | --- | --- |"]
    lignes += [
        f"| 0,00 | {code} | {taux} | 0,00 |" for code, taux in taux_par_code.items()
    ]
    lignes.append(f"| {total_ht} |  |  | 0,00 |")
    return "\n".join(lignes)


def _entete_minimal(*, client: str = "CLIENT INVENTE") -> str:
    return (
        "FOURNISSEUR INVENTE\n\n"
        "FACTURE N°INV0001\n\n"
        "Date : 01/08/2026\n\n"
        "Page : 1 / 1\n\n"
        f"{client}\n\n"
        ".../..."
    )


def _page(markdown: str, *tables_contenu: str) -> dict[str, Any]:
    """Une page OCR inventée. `blocks` reconstruit le texte complet (en-tête
    + tableaux) comme le fait la vraie réponse Mistral OCR, où `markdown`
    seul ne référence les tableaux que par un lien (voir `ocr._texte_page`)."""
    blocs = ([{"content": markdown}] if markdown else []) + [
        {"content": c} for c in tables_contenu
    ]
    return {
        "markdown": markdown,
        "tables": [{"format": "markdown", "content": c} for c in tables_contenu],
        "blocks": blocs,
    }


def _reponse(*pages: dict[str, Any]) -> dict[str, Any]:
    return {"pages": list(pages)}


def _facture_simple(
    lignes_donnees: list[str],
    total_ht: str,
    taux_par_code: dict[str, str] | None = None,
    client: str = "CLIENT INVENTE",
) -> dict[str, Any]:
    page = _page(
        _entete_minimal(client=client),
        _table(*lignes_donnees),
        _recap(total_ht, taux_par_code),
    )
    return _reponse(page)


_MARQUEUR_BLOC_INVENTE = "Concerne le B.L. n°L1 du 01/08/2026 (Commande n°V1) - VILLE"
_LIGNE_MARQUEUR_BLOC_1 = _ligne(_MARQUEUR_BLOC_INVENTE, "", "", "", "", "", "", "")
_LIGNE_ARTICLE_1 = _ligne(
    "ART1", "ARTICLE INVENTE", "1,00", "1,00", "10,00", "10,00", "10,00", "5"
)


# --------------------------------------------------------------------------
# En-tête de facture (fournisseur, numéro, date, client, échéance)
# --------------------------------------------------------------------------


def test_entete_facture_fournisseur_numero_date_client() -> None:
    lignes = [_LIGNE_MARQUEUR_BLOC_1, _LIGNE_ARTICLE_1]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="10,00"))

    assert facture.fournisseur_brut == "FOURNISSEUR INVENTE"
    assert facture.numero == "INV0001"
    assert facture.date_facture == date(2026, 8, 1)
    assert facture.client == "CLIENT INVENTE"


def test_fournisseur_ignore_les_lignes_avec_chiffres_du_bandeau() -> None:
    """Une ligne administrative qui reprend le nom (SIRET, TVA...) contient
    des chiffres : elle ne doit jamais être prise pour la raison sociale."""
    entete = (
        "FOURNISSEUR INVENTE, SAS AU CAPITAL DE 10 000 EUR SIRET 12345678901234\n\n"
        "FOURNISSEUR INVENTE\n\n"
        "FACTURE N°INV0001\n\n"
        "Date : 01/08/2026\n\n"
        "Page : 1 / 1\n\n"
        "CLIENT INVENTE\n\n"
        ".../..."
    )
    page = _page(
        entete, _table(_LIGNE_MARQUEUR_BLOC_1, _LIGNE_ARTICLE_1), _recap("10,00")
    )

    facture = analyser_facture_unikalo(_reponse(page))

    assert facture.fournisseur_brut == "FOURNISSEUR INVENTE"


def test_client_avec_titre_markdown_est_nettoye() -> None:
    """L'OCR rend parfois la première ligne du bloc adresse comme un titre
    markdown (« # NOM »), observé sur la fixture réelle : le « # » doit être
    retiré."""
    lignes = [_LIGNE_MARQUEUR_BLOC_1, _LIGNE_ARTICLE_1]

    facture = analyser_facture_unikalo(
        _facture_simple(lignes, total_ht="10,00", client="# CLIENT AVEC TITRE")
    )

    assert facture.client == "CLIENT AVEC TITRE"


# --------------------------------------------------------------------------
# Conversion des nombres français (bout en bout, via le parseur)
# --------------------------------------------------------------------------


def test_conversion_nombre_francais_avec_milliers_et_signe_negatif() -> None:
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne(
            "ART1",
            "ARTICLE INVENTE",
            "1,000",
            "1 234,000",
            "1 234,56",
            "1 234,56",
            "-1 234,56",
            "5",
        ),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="-1 234,56"))

    ligne = facture.blocs[0].lignes[0]
    assert ligne.qte_totale == Decimal("1234")
    assert ligne.pu_ht == Decimal("1234.56")
    assert ligne.montant_ht == Decimal("-1234.56")
    assert facture.total_ht == Decimal("-1234.56")


# --------------------------------------------------------------------------
# Classification des lignes
# --------------------------------------------------------------------------


def test_ligne_eco_participation_est_classee_eco() -> None:
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne("", "ECO-PARTICIPATION", "1,00", "1,00", "0,10", "0,10", "0,10", "5"),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="0,10"))

    assert facture.blocs[0].lignes[0].type_ligne is TypeLigne.ECO


def test_ligne_a_montant_negatif_reste_de_type_article() -> None:
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne(
            "ART1", "ARTICLE AVOIR", "-1,000", "-1,000", "10,00", "10,00", "-10,00", "5"
        ),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="-10,00"))

    ligne = facture.blocs[0].lignes[0]
    assert ligne.type_ligne is TypeLigne.ARTICLE
    assert ligne.montant_ht is not None
    assert ligne.montant_ht < 0


def test_commentaire_retrait_pas_de_bon_est_isole_sans_montant() -> None:
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne("", "RETRAIT MARCHANDISE PAS DE BON", "", "", "", "", "", ""),
        _LIGNE_ARTICLE_1,
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="10,00"))

    bloc = facture.blocs[0]
    commentaire = next(
        ligne for ligne in bloc.lignes if ligne.type_ligne is TypeLigne.COMMENTAIRE
    )
    assert commentaire.montant_ht is None
    assert commentaire.code_article is None
    assert len(bloc.commentaires) == 1
    assert "RETRAIT" in bloc.commentaires[0]
    assert "PAS DE BON" in bloc.commentaires[0]


def test_remise_100_pourcent_sans_montant_imprime() -> None:
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne("ART1", "ARTICLE OFFERT", "", "", "", "", "", ""),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="0,00"))

    ligne = facture.blocs[0].lignes[0]
    assert ligne.montant_ht is None
    assert ligne.remise_pct == Decimal("100")


def test_pourcentage_explicite_dans_une_cellule_de_prix() -> None:
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne(
            "ART1", "ARTICLE REMISE PARTIELLE", "1,00", "1,00", "10,00", "100%", "", "5"
        ),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="0,00"))

    ligne = facture.blocs[0].lignes[0]
    assert ligne.remise_pct == Decimal("100")
    assert ligne.pu_cdt is None
    assert ligne.montant_ht is None


def test_recapitulatif_tva_illisible_donne_tva_none_partout() -> None:
    """R6 assoupli : un code TVA qui ne résout à aucun taux lisible dans le
    récapitulatif (ici un taux non numérique) laisse `tva=None`, sans faire
    échouer l'analyse (le total HT, lui, reste lisible sur la ligne finale)."""
    lignes = [_LIGNE_MARQUEUR_BLOC_1, _LIGNE_ARTICLE_1]

    facture = analyser_facture_unikalo(
        _facture_simple(lignes, total_ht="10,00", taux_par_code={"5": "N/A"})
    )

    assert all(ligne.tva is None for bloc in facture.blocs for ligne in bloc.lignes)


# --------------------------------------------------------------------------
# Blocs B.L.
# --------------------------------------------------------------------------


def test_deux_blocs_concerne_le_bl_distincts() -> None:
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne(
            "ART1", "ARTICLE BLOC UN", "1,00", "1,00", "10,00", "10,00", "10,00", "5"
        ),
        _ligne(
            "Concerne le B.L. n°L2 du 02/08/2026 (Commande n°V2) - AUTRE VILLE",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ),
        _ligne(
            "ART2", "ARTICLE BLOC DEUX", "1,00", "1,00", "5,00", "5,00", "5,00", "5"
        ),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="15,00"))

    assert len(facture.blocs) == 2
    assert facture.blocs[0].numero_bl == "L1"
    assert facture.blocs[0].date_bl == date(2026, 8, 1)
    assert facture.blocs[1].numero_bl == "L2"
    assert len(facture.blocs[0].lignes) == 1
    assert len(facture.blocs[1].lignes) == 1


def test_bloc_a_cheval_sur_deux_pages() -> None:
    page1 = _page(
        _entete_minimal(),
        _table(
            _LIGNE_MARQUEUR_BLOC_1,
            _ligne(
                "ART1",
                "ARTICLE PAGE UN",
                "1,00",
                "1,00",
                "10,00",
                "10,00",
                "10,00",
                "5",
            ),
        ),
    )
    page2 = _page(
        "",
        _table(
            _ligne(
                "ART2", "ARTICLE PAGE DEUX", "1,00", "1,00", "5,00", "5,00", "5,00", "5"
            ),
        ),
        _recap("15,00"),
    )

    facture = analyser_facture_unikalo(_reponse(page1, page2))

    assert len(facture.blocs) == 1
    assert len(facture.blocs[0].lignes) == 2


def test_entete_de_colonnes_repete_nest_jamais_compte_comme_ligne() -> None:
    page1 = _page(
        _entete_minimal(),
        _table(
            _LIGNE_MARQUEUR_BLOC_1,
            _ligne(
                "ART1", "ARTICLE UNIQUE", "1,00", "1,00", "10,00", "10,00", "10,00", "5"
            ),
        ),
    )
    # Page 2 : en-tête de colonnes et séparateur seuls (répétés par l'OCR),
    # aucune ligne de données.
    page2 = _page("", _table(), _recap("10,00"))

    facture = analyser_facture_unikalo(_reponse(page1, page2))

    assert len(facture.blocs) == 1
    assert len(facture.blocs[0].lignes) == 1


def test_lignes_apres_conditions_de_reglement_sont_ignorees() -> None:
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne(
            "ART1",
            "ARTICLE AVANT CONDITIONS",
            "1,00",
            "1,00",
            "10,00",
            "10,00",
            "10,00",
            "5",
        ),
        _ligne(
            "",
            "Conditions de règlement : Echéance au 30/09/2026",
            "",
            "",
            "",
            "",
            "",
            "",
        ),
        _ligne(
            "ART2",
            "ARTICLE APRES CONDITIONS IGNORE",
            "1,00",
            "1,00",
            "99,00",
            "99,00",
            "99,00",
            "5",
        ),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="10,00"))

    bloc = facture.blocs[0]
    assert len(bloc.lignes) == 1
    assert bloc.lignes[0].designation == "ARTICLE AVANT CONDITIONS"
    assert facture.echeance == date(2026, 9, 30)


# --------------------------------------------------------------------------
# Les 3 formes de fusion observées sur la fixture réelle
# --------------------------------------------------------------------------


def test_forme_fusion_1_cellule_numerique_empilee() -> None:
    """Deux lignes source fusionnées par l'OCR : chaque colonne numérique
    porte deux valeurs séparées par un espace."""
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne(
            "ART1",
            "ARTICLE EMPILE",
            "1,000",
            "2,000",
            "10,00 20,00",
            "10,00 20,00",
            "10,00 40,00",
            "5 5",
        ),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="50,00"))

    bloc = facture.blocs[0]
    assert len(bloc.lignes) == 2
    montants = sorted(
        ligne.montant_ht for ligne in bloc.lignes if ligne.montant_ht is not None
    )
    assert montants == [Decimal("10.00"), Decimal("40.00")]


def test_forme_fusion_2_marqueur_de_bloc_et_montant_sur_la_meme_ligne() -> None:
    """Forme empirique observée sur la fixture réelle : cellule ARTICLE
    vide, le marqueur de bloc ET la désignation vivent dans la même cellule
    DÉSIGNATION. La ligne compte à la fois comme début de bloc ET comme
    ligne chiffrée."""
    lignes = [
        _ligne(
            "",
            f"{_MARQUEUR_BLOC_INVENTE} ARTICLE FUSIONNE AVEC LE MARQUEUR",
            "1,00",
            "1,00",
            "10,00",
            "10,00",
            "10,00",
            "5",
        ),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="10,00"))

    assert len(facture.blocs) == 1
    bloc = facture.blocs[0]
    assert bloc.numero_bl == "L1"
    assert len(bloc.lignes) == 1
    assert bloc.lignes[0].montant_ht == Decimal("10.00")
    assert bloc.lignes[0].code_article is None


def test_forme_fusion_2_variante_avec_code_article_present() -> None:
    """Variante de robustesse (non observée telle quelle sur la fixture
    réelle, où la cellule ARTICLE est systématiquement vide dans ce cas) :
    le parseur doit rester correct même si un code article propre
    accompagne la fusion marqueur + montant."""
    lignes = [
        _ligne(
            "ART1",
            f"{_MARQUEUR_BLOC_INVENTE} ARTICLE FUSIONNE AVEC LE MARQUEUR",
            "1,00",
            "1,00",
            "10,00",
            "10,00",
            "10,00",
            "5",
        ),
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="10,00"))

    assert len(facture.blocs) == 1
    bloc = facture.blocs[0]
    assert bloc.numero_bl == "L1"
    assert len(bloc.lignes) == 1
    assert bloc.lignes[0].montant_ht == Decimal("10.00")
    assert bloc.lignes[0].code_article == "ART1"


def test_forme_fusion_3_mention_chantier_mal_separee_devient_commentaire() -> None:
    """Une mention CHANTIER sans « : ... (code) » propre n'est pas reconnue
    comme marqueur : elle retombe en commentaire plutôt que de faire échouer
    l'analyse (`chantier_brut` reste `None` pour ce bloc)."""
    lignes = [
        _LIGNE_MARQUEUR_BLOC_1,
        _ligne(
            "",
            "CHANTIER SANS CODE RETRAIT MARCHANDISE PAS DE BON",
            "",
            "",
            "",
            "",
            "",
            "",
        ),
        _LIGNE_ARTICLE_1,
    ]

    facture = analyser_facture_unikalo(_facture_simple(lignes, total_ht="10,00"))

    bloc = facture.blocs[0]
    assert bloc.chantier_brut is None
    assert any("CHANTIER" in c for c in bloc.commentaires)
    assert len(bloc.lignes) == 2


# --------------------------------------------------------------------------
# Structures non reconnues -> FactureIllisible
# --------------------------------------------------------------------------


def test_reponse_sans_pages_leve_facture_illisible() -> None:
    with pytest.raises(FactureIllisible):
        analyser_facture_unikalo({"pages": []})


def test_reponse_sans_concerne_le_bl_leve_facture_illisible() -> None:
    lignes = [
        _ligne(
            "ART1", "ARTICLE SANS BLOC", "1,00", "1,00", "10,00", "10,00", "10,00", "5"
        ),
    ]

    with pytest.raises(FactureIllisible):
        analyser_facture_unikalo(_facture_simple(lignes, total_ht="10,00"))


def test_reponse_sans_total_ht_leve_facture_illisible() -> None:
    page = _page(
        _entete_minimal(),
        _table(_LIGNE_MARQUEUR_BLOC_1, _LIGNE_ARTICLE_1),
        # Pas de tableau récapitulatif : le total HT est introuvable.
    )

    with pytest.raises(FactureIllisible):
        analyser_facture_unikalo(_reponse(page))


# --------------------------------------------------------------------------
# Tests génériques sur les vraies fixtures OCR (skip si absentes)
# --------------------------------------------------------------------------

_DOSSIER_FIXTURES = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "unikalo"
)
_FICHIERS_FIXTURES_OCR: Sequence[Path | None] = sorted(
    _DOSSIER_FIXTURES.glob("*.mistral-ocr.json")
)
_MARQUEUR_BL_INDEPENDANT_RE = re.compile(r"concerne\s+le\s+b\.?\s*l\.?", re.IGNORECASE)


@pytest.fixture(params=_FICHIERS_FIXTURES_OCR or [None])
def reponse_ocr_reelle(request: pytest.FixtureRequest) -> dict[str, Any]:
    chemin: Path | None = request.param
    if chemin is None:
        pytest.skip(
            "aucune fixture *.mistral-ocr.json dans tests/fixtures/unikalo/ "
            "(clone neuf ou fixtures non déposées)"
        )
    donnees: dict[str, Any] = json.loads(chemin.read_text(encoding="utf-8"))
    return donnees


@pytest.fixture
def facture_reelle(reponse_ocr_reelle: dict[str, Any]) -> Any:
    return analyser_facture_unikalo(reponse_ocr_reelle)


def test_fixture_reelle_ecart_somme_montants_dans_la_tolerance(
    facture_reelle: Any,
) -> None:
    somme = sum(
        (
            ligne.montant_ht
            for bloc in facture_reelle.blocs
            for ligne in bloc.lignes
            if ligne.montant_ht is not None
        ),
        Decimal("0"),
    )
    ecart = abs(somme - facture_reelle.total_ht)

    assert ecart <= Decimal("0.05"), "écart de réconciliation hors tolérance (0,05 €)"


def test_fixture_reelle_nombre_de_blocs_egale_occurrences_du_marqueur(
    reponse_ocr_reelle: dict[str, Any], facture_reelle: Any
) -> None:
    texte = texte_ocr(reponse_ocr_reelle)
    occurrences = len(_MARQUEUR_BL_INDEPENDANT_RE.findall(texte))

    assert len(facture_reelle.blocs) == occurrences


def test_fixture_reelle_chaque_bloc_est_numerote_et_date(facture_reelle: Any) -> None:
    assert facture_reelle.blocs
    for bloc in facture_reelle.blocs:
        assert bloc.numero_bl != ""
        assert bloc.date_bl is not None


def test_fixture_reelle_presence_eco_negative_et_commentaire(
    facture_reelle: Any,
) -> None:
    toutes_lignes = [ligne for bloc in facture_reelle.blocs for ligne in bloc.lignes]

    assert any(ligne.type_ligne is TypeLigne.ECO for ligne in toutes_lignes)
    assert any(
        ligne.montant_ht is not None and ligne.montant_ht < 0 for ligne in toutes_lignes
    )
    assert any(ligne.type_ligne is TypeLigne.COMMENTAIRE for ligne in toutes_lignes)


# --------------------------------------------------------------------------
# R19 — non-régression contre un fichier de référence <nom>.attendu.json
# --------------------------------------------------------------------------


def _normaliser_espaces(texte: str | None) -> str:
    return " ".join((texte or "").split())


def _paires_ocr_et_attendu() -> list[tuple[Path, Path]]:
    paires = []
    for chemin_ocr in sorted(_DOSSIER_FIXTURES.glob("*.mistral-ocr.json")):
        nom = chemin_ocr.name.removesuffix(".mistral-ocr.json")
        chemin_attendu = _DOSSIER_FIXTURES / f"{nom}.attendu.json"
        if chemin_attendu.exists():
            paires.append((chemin_ocr, chemin_attendu))
    return paires


_PairesReference = Sequence[tuple[Path, Path] | None]
_PAIRES_REFERENCE: _PairesReference = _paires_ocr_et_attendu() or [None]


@pytest.fixture(params=_PAIRES_REFERENCE)
def paire_reference(
    request: pytest.FixtureRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    paire: tuple[Path, Path] | None = request.param
    if paire is None:
        pytest.skip(
            "aucune paire <nom>.mistral-ocr.json / <nom>.attendu.json dans "
            "tests/fixtures/unikalo/ (fichier de référence R19 non déposé)"
        )
    chemin_ocr, chemin_attendu = paire
    reponse: dict[str, Any] = json.loads(chemin_ocr.read_text(encoding="utf-8"))
    attendu: dict[str, Any] = json.loads(chemin_attendu.read_text(encoding="utf-8"))
    return reponse, attendu


def test_reference_entete_conforme(
    paire_reference: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    reponse, attendu = paire_reference
    facture = analyser_facture_unikalo(reponse)
    attendu_entete = attendu["entete"]

    ecarts = []
    if facture.fournisseur_brut != attendu_entete["fournisseur_brut"]:
        ecarts.append("fournisseur_brut")
    if facture.numero != attendu_entete["numero"]:
        ecarts.append("numero")
    if facture.date_facture.isoformat() != attendu_entete["date_facture"]:
        ecarts.append("date_facture")
    if facture.client != attendu_entete["client"]:
        ecarts.append("client")
    echeance_iso = facture.echeance.isoformat() if facture.echeance else None
    if echeance_iso != attendu_entete["echeance"]:
        ecarts.append("echeance")

    assert not ecarts, f"champs d'en-tête en écart avec la référence : {ecarts}"


def test_reference_blocs_conformes(
    paire_reference: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    reponse, attendu = paire_reference
    facture = analyser_facture_unikalo(reponse)
    blocs_attendus = attendu["blocs"]

    assert len(facture.blocs) == len(blocs_attendus), (
        "nombre de blocs en écart avec la référence"
    )

    ecarts: list[tuple[int, str]] = []
    for index, (bloc, attendu_bloc) in enumerate(
        zip(facture.blocs, blocs_attendus, strict=True)
    ):
        if bloc.numero_bl != attendu_bloc["numero_bl"]:
            ecarts.append((index, "numero_bl"))
        date_bl_iso = bloc.date_bl.isoformat() if bloc.date_bl else None
        if date_bl_iso != attendu_bloc["date_bl"]:
            ecarts.append((index, "date_bl"))
        if _normaliser_espaces(bloc.chantier_brut) != _normaliser_espaces(
            attendu_bloc["chantier_brut"]
        ):
            ecarts.append((index, "chantier_brut"))
        if bloc.montant_ht != Decimal(attendu_bloc["montant_ht"]):
            ecarts.append((index, "montant_ht"))

    assert not ecarts, f"blocs en écart avec la référence (index, champ) : {ecarts}"
