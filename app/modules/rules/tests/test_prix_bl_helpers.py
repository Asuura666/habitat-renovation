"""Tests des aides communes aux règles de prix des bons (`rules.rules.
_prix_bl`, phase 3, R19 à R25). Données inventées."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.rules.rules._prix_bl import (
    TIRET,
    candidats_ou_tiret,
    ecart_pct,
    mois_ecoules,
)


def test_ecart_pct_hausse_positive() -> None:
    assert ecart_pct(Decimal("7.90"), Decimal("7.50")) == Decimal("5.3")


def test_ecart_pct_baisse_negative() -> None:
    assert ecart_pct(Decimal("6.80"), Decimal("7.50")) == Decimal("-9.3")


def test_ecart_pct_egalite() -> None:
    assert ecart_pct(Decimal("7.50"), Decimal("7.50")) == Decimal("0.0")


def test_candidats_ou_tiret_vide() -> None:
    assert candidats_ou_tiret(()) == TIRET


def test_candidats_ou_tiret_plusieurs() -> None:
    assert candidats_ou_tiret(("Cloison 48", "Cloison 90")) == "Cloison 48 / Cloison 90"


def test_mois_ecoules_mois_pleins() -> None:
    assert mois_ecoules(date(2025, 1, 1), date(2026, 1, 1)) == 12


def test_mois_ecoules_fin_de_mois_pas_encore_plein() -> None:
    """31 janvier -> 28 février : le mois n'est pas encore plein (28 < 31),
    contrairement à un simple compte de mois calendaires (qui donnerait
    1)."""
    assert mois_ecoules(date(2026, 1, 31), date(2026, 2, 28)) == 0


def test_mois_ecoules_meme_jour() -> None:
    assert mois_ecoules(date(2026, 1, 15), date(2026, 3, 15)) == 2
