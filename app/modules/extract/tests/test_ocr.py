"""Tests des utilitaires génériques de lecture OCR (`ocr.py`).

Aucune connaissance d'un fournisseur en particulier ici (voir `unikalo.py`
et `test_unikalo.py` pour le parseur Unikalo). Données entièrement
inventées, tournent toujours.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.extract.ocr import (
    date_fr,
    decimal_fr,
    decouper_ligne_tableau,
    diviser_valeurs_empilees,
    est_ligne_empilee,
    est_separateur,
    pourcentage_fr,
    tables_de_page,
    texte_ocr,
)

# --------------------------------------------------------------------------
# texte_ocr
# --------------------------------------------------------------------------


def test_texte_ocr_concatene_les_pages_markdown_quand_pas_de_blocs() -> None:
    reponse = {"pages": [{"markdown": "PAGE UN"}, {"markdown": "PAGE DEUX"}]}

    assert texte_ocr(reponse) == "PAGE UN\nPAGE DEUX"


def test_texte_ocr_reconstruit_les_tableaux_via_les_blocs_quand_presents() -> None:
    """`markdown` ne référence les tableaux que par un lien (`tbl-0.md`) :
    `texte_ocr` doit se rabattre sur `blocks`, qui restitue le texte complet."""
    reponse = {
        "pages": [
            {
                "markdown": "[Tableau](tbl-0.md)",
                "blocks": [{"content": "SEGMENT UN"}, {"content": "SEGMENT DEUX"}],
            }
        ]
    }

    assert texte_ocr(reponse) == "SEGMENT UN\nSEGMENT DEUX"


def test_texte_ocr_reponse_sans_pages() -> None:
    assert texte_ocr({}) == ""
    assert texte_ocr({"pages": []}) == ""


# --------------------------------------------------------------------------
# Conversion de nombres et de dates français
# --------------------------------------------------------------------------


def test_decimal_fr_milliers_et_signe_negatif() -> None:
    assert decimal_fr("1 234,56") == Decimal("1234.56")
    assert decimal_fr("-1 234,56") == Decimal("-1234.56")
    assert decimal_fr("") is None
    assert decimal_fr("abc") is None


def test_pourcentage_fr_extrait_le_nombre_avant_le_signe() -> None:
    assert pourcentage_fr("(20%)") == Decimal("20")
    assert pourcentage_fr("100%") == Decimal("100")
    assert pourcentage_fr("sans pourcentage") is None


def test_date_fr_convertit_jj_mm_aaaa() -> None:
    assert date_fr("01/08/2026") == date(2026, 8, 1)
    assert date_fr("pas une date") is None


# --------------------------------------------------------------------------
# Lecture de tableau markdown
# --------------------------------------------------------------------------


def test_decouper_ligne_tableau() -> None:
    assert decouper_ligne_tableau("| a | b | c |") == ["a", "b", "c"]
    assert decouper_ligne_tableau("pas une ligne de tableau") is None


def test_est_separateur() -> None:
    assert est_separateur(["---", "---", "---"])
    assert not est_separateur(["a", "---"])
    assert not est_separateur(["", ""])


def test_tables_de_page() -> None:
    page = {"tables": [{"format": "markdown", "content": "| a |"}]}
    assert tables_de_page(page) == ["| a |"]
    assert tables_de_page({}) == []


# --------------------------------------------------------------------------
# Cellules empilées (fusion OCR de deux lignes source)
# --------------------------------------------------------------------------


def test_est_ligne_empilee_distingue_un_seul_nombre_a_milliers() -> None:
    # Un seul nombre avec séparateur de milliers : pas empilé.
    assert not est_ligne_empilee(["12 345,67", "1,00"])
    # Deux nombres décimaux distincts dans une même valeur : empilé.
    assert est_ligne_empilee(["10,00 20,00", "1,00"])


def test_diviser_valeurs_empilees_zippe_les_colonnes() -> None:
    resultat = diviser_valeurs_empilees(["1,00 2,00", "10,00 20,00", "5"])

    assert resultat == [["1,00", "10,00", "5"], ["2,00", "20,00", "5"]]
