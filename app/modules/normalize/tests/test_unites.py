"""Tests de `normaliser_unite` (`unites.py`)."""

from __future__ import annotations

from app.modules.normalize.unites import NatureUnite, Unite, normaliser_unite


def test_normaliser_unite_mesure_connue_insensible_casse_et_espaces() -> None:
    assert normaliser_unite(" Kgs ") == Unite(code="kg", nature=NatureUnite.MESURE)


def test_normaliser_unite_conditionnement_connu() -> None:
    assert normaliser_unite("SEAUX") == Unite(
        code="seau", nature=NatureUnite.CONDITIONNEMENT
    )


def test_normaliser_unite_bag_reconnu_comme_sac() -> None:
    """L3-D26, constat 11 : Point.P imprime « BAG » (sac)."""
    assert normaliser_unite("BAG") == Unite(
        code="sac", nature=NatureUnite.CONDITIONNEMENT
    )
    assert normaliser_unite("bags") == Unite(
        code="sac", nature=NatureUnite.CONDITIONNEMENT
    )


def test_normaliser_unite_metre_carre_symbole_exposant() -> None:
    assert normaliser_unite("M²") == Unite(code="m2", nature=NatureUnite.MESURE)


def test_normaliser_unite_inconnue_renvoie_none() -> None:
    assert normaliser_unite("XYZ") is None


def test_normaliser_unite_none_renvoie_none() -> None:
    assert normaliser_unite(None) is None
