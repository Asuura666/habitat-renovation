"""Tests de `normaliser_libelle` et `ressemblance` (`texte.py`)."""

from __future__ import annotations

from app.modules.normalize.texte import normaliser_libelle, ressemblance


def test_normaliser_libelle_retire_accents_et_casefold() -> None:
    assert normaliser_libelle("Chantier : Résidence Été") == "chantier residence ete"


def test_normaliser_libelle_ponctuation_devient_espace_et_se_reduit() -> None:
    assert normaliser_libelle("  ORMEAUX   (9944126862) ") == "ormeaux 9944126862"


def test_normaliser_libelle_none_renvoie_chaine_vide() -> None:
    assert normaliser_libelle(None) == ""


def test_ressemblance_ignore_casse_accents_ponctuation() -> None:
    assert ressemblance("Résidence des Tilleuls", "RESIDENCE DES TILLEULS") == 100


def test_ressemblance_ignore_ordre_des_mots() -> None:
    assert ressemblance("Tilleuls résidence", "Résidence Tilleuls") == 100


def test_ressemblance_vide_vaut_zero() -> None:
    assert ressemblance("", "Villa Test") == 0
    assert ressemblance(None, "Villa Test") == 0


def test_ressemblance_est_un_entier_arrondi_vers_le_bas() -> None:
    # "villa tes" / "villa test" : 2*9/19 = 94,7 -> 94
    assert ressemblance("Villa tes", "Villa test") == 94
