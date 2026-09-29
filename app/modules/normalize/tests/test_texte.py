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


# --- nombres_differents (B-05) ---


def test_nombres_differents_paires_numerotees() -> None:
    from app.modules.normalize.texte import nombres_differents

    assert nombres_differents("Lot 12", "Lot 13") is True
    assert nombres_differents("Résidence Les Pins 2", "Résidence Les Pins 3") is True
    assert nombres_differents("Bât A 3", "Bât A 4") is True
    assert nombres_differents("Immeuble Les Acacias 10", "Immeuble Les Acacias 110")


def test_nombres_differents_memes_nombres_ou_aucun() -> None:
    from app.modules.normalize.texte import nombres_differents

    assert nombres_differents("Villa Test", "VILLA TEST") is False
    assert nombres_differents("Lot 12", "lot 12") is False
    assert nombres_differents("Lot 12 Bât A", "bat a - lot 12") is False
    assert nombres_differents("Lot 03", "Lot 3") is False
    assert nombres_differents("Les Pins", "Les Pins 2") is True
    assert nombres_differents(None, "Lot 1") is True
    assert nombres_differents(None, None) is False
