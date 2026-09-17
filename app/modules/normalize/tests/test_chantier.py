"""Tests de `decomposer_chantier` (`chantier.py`, L3-D6)."""

from __future__ import annotations

from app.modules.normalize.chantier import LibelleChantier, decomposer_chantier


def test_decomposer_chantier_retire_prefixe_et_extrait_le_code() -> None:
    assert decomposer_chantier("Chantier : Maison Test (99-001)") == LibelleChantier(
        libelle="maison test", code="99-001"
    )


def test_decomposer_chantier_sans_prefixe_ni_code() -> None:
    assert decomposer_chantier("Maison Test") == LibelleChantier(
        libelle="maison test", code=None
    )


def test_decomposer_chantier_parentheses_au_milieu_non_retirees() -> None:
    assert decomposer_chantier("Maison (Test) Dupont") == LibelleChantier(
        libelle="maison test dupont", code=None
    )


def test_decomposer_chantier_accents_et_casse() -> None:
    assert decomposer_chantier("Chantier : Résidence Été") == LibelleChantier(
        libelle="residence ete", code=None
    )


def test_decomposer_chantier_libelle_vide_renvoie_none() -> None:
    assert decomposer_chantier("(99-001)") is None


def test_decomposer_chantier_none_renvoie_none() -> None:
    assert decomposer_chantier(None) is None
