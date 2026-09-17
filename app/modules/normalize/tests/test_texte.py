"""Tests de `normaliser_libelle` (`texte.py`)."""

from __future__ import annotations

from app.modules.normalize.texte import normaliser_libelle


def test_normaliser_libelle_retire_accents_et_casefold() -> None:
    assert normaliser_libelle("Chantier : Résidence Été") == "chantier residence ete"


def test_normaliser_libelle_ponctuation_devient_espace_et_se_reduit() -> None:
    assert normaliser_libelle("  ORMEAUX   (9944126862) ") == "ormeaux 9944126862"


def test_normaliser_libelle_none_renvoie_chaine_vide() -> None:
    assert normaliser_libelle(None) == ""
