"""Tests de `extract/arithmetique.py` (A6, lot 2 du 31/10/2026) : contrôle
quantité x prix unitaire = montant. Données inventées."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.extract.arithmetique import controle_arithmetique_ligne

D = Decimal


@pytest.mark.parametrize(
    ("quantite", "pu", "montant"),
    [
        ("500", "0.4692", "234.60"),  # prix à 4 décimales
        ("5", "10.21", "51.05"),
        ("2.5", "12.30", "30.75"),  # quantité décimale
        ("3", "0.3333", "1.00"),  # 0,9999 arrondi au centime
        ("500", "0.46923", "234.62"),  # 234,615 arrondi commercial vers le haut
        ("500", "0.4692", "234.61"),  # un centime d'écart toléré
        ("0", "10", "0"),
    ],
)
def test_controle_passe(quantite: str, pu: str, montant: str) -> None:
    assert controle_arithmetique_ligne(D(quantite), D(pu), D(montant)) is True


@pytest.mark.parametrize(
    ("quantite", "pu", "montant"),
    [
        ("1", "10.21", "51.05"),
        ("500", "0.4692", "234.63"),
        ("5", "10.21", "5.10"),
    ],
)
def test_controle_echoue(quantite: str, pu: str, montant: str) -> None:
    assert controle_arithmetique_ligne(D(quantite), D(pu), D(montant)) is False


@pytest.mark.parametrize(
    ("quantite", "pu", "montant"),
    [(None, D("1"), D("1")), (D("1"), None, D("1")), (D("1"), D("1"), None)],
)
def test_controle_impossible_si_une_valeur_manque(
    quantite: Decimal | None, pu: Decimal | None, montant: Decimal | None
) -> None:
    assert controle_arithmetique_ligne(quantite, pu, montant) is None
