"""Tests de `extract/arithmetique.py` (A6, lot 2 du 31/10/2026) : contrôle
quantité x prix unitaire = montant. Données inventées."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.extract.arithmetique import (
    controle_arithmetique_ligne,
    decimales_du_brut,
    produit_attendu,
)

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
        ("100", "0.888", "88.75"),  # prix imprimé arrondi (vrai prix 0,8875)
    ],
)
def test_controle_passe(quantite: str, pu: str, montant: str) -> None:
    assert controle_arithmetique_ligne(D(quantite), D(pu), D(montant)) is True


@pytest.mark.parametrize(
    ("quantite", "pu", "montant"),
    [
        ("1", "10.21", "51.05"),
        ("500", "0.4692", "234.70"),
        ("5", "10.21", "5.10"),
        ("6", "14.80", "89.70"),
        ("4", "3.08", "12.24"),  # écart 0,08 > tolérance 0,03
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


def test_les_decimales_du_prix_lu_donnent_la_tolerance() -> None:
    # 100 x 0,888 = 88,80 ; 88,75 passe à 3 décimales (tolérance 0,06) mais
    # pas si le prix était lu à 6 décimales (tolérance 0,01).
    assert controle_arithmetique_ligne(D("100"), D("0.888"), D("88.75")) is True
    assert (
        controle_arithmetique_ligne(D("100"), D("0.888"), D("88.75"), decimales_pu=6)
        is False
    )


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("0,888", 3),
        ("14,80", 2),
        ("0,4692", 4),
        ("1 234,50", 2),
        ("12", 0),
        ("12.5", 1),
        (None, None),
        ("abc", None),
    ],
)
def test_decimales_du_brut(brut: str | None, attendu: int | None) -> None:
    assert decimales_du_brut(brut) == attendu


def test_produit_attendu_arrondi_commercial_au_centime() -> None:
    assert produit_attendu(D("6"), D("14.80")) == D("88.80")
    assert produit_attendu(D("500"), D("0.46923")) == D("234.62")
