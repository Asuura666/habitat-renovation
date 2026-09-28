"""Tests de R21 — moins cher que la grille (phase 3, prix des bons).
Données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import (
    Gravite,
    LignePrixBl,
    ParametresPrixBl,
    ReferencePrix,
)
from app.modules.rules.rules.R21 import R21

DOC = uuid.UUID(int=1)
LIGNE = uuid.UUID(int=2)


def _grille(**overrides: Any) -> ReferencePrix:
    base: dict[str, Any] = {
        "prix": Decimal("7.50"),
        "unite": "u",
        "date": date(2026, 1, 1),
        "comparable": True,
        "methode": "reference",
        "ressemblance": 100,
        "designation": "Plaque std 13",
        "source": "grille",
    }
    base.update(overrides)
    return ReferencePrix(**base)


def _ligne(**overrides: Any) -> LignePrixBl:
    base: dict[str, Any] = {
        "document_id": DOC,
        "ligne_id": LIGNE,
        "designation": "Plaque std 13",
        "code": "PLQ13",
        "prix_bon": Decimal("6.80"),
        "unite_bon": "u",
        "date_bon": date(2026, 8, 1),
        "grille": _grille(),
        "candidats": (),
        "dernier_prix": None,
    }
    base.update(overrides)
    return LignePrixBl(**base)


def test_R21_positif_detail_complet() -> None:
    anomalie = R21(_ligne(), ParametresPrixBl())

    assert anomalie is not None
    assert anomalie.regle == "R21" and anomalie.gravite is Gravite.BASSE
    assert anomalie.document_id == DOC and anomalie.ligne_id == LIGNE
    assert anomalie.detail["produit"] == "Plaque std 13"
    assert anomalie.detail["prix_bon"] == "6.80"
    assert anomalie.detail["prix_grille"] == "7.50"
    assert anomalie.detail["ecart_pct"] == "-9.3"


def test_R21_negatif_prix_egal() -> None:
    assert R21(_ligne(prix_bon=Decimal("7.50")), ParametresPrixBl()) is None


def test_R21_limite_exacte_du_seuil_ne_declenche_rien() -> None:
    """Seuil de baisse par défaut : 5 %. Exactement à la limite (7,50 *
    0,95 = 7,125) -> aucune anomalie."""
    ligne = _ligne(prix_bon=Decimal("7.125"))

    assert R21(ligne, ParametresPrixBl()) is None
    assert R21(_ligne(prix_bon=Decimal("7.124")), ParametresPrixBl()) is not None


def test_R21_sans_grille_ne_declenche_rien() -> None:
    assert R21(_ligne(grille=None), ParametresPrixBl()) is None


def test_R21_reference_non_comparable_ne_declenche_rien() -> None:
    ligne = _ligne(
        prix_bon=Decimal("0.01"), grille=_grille(comparable=False, prix=Decimal("100"))
    )
    assert R21(ligne, ParametresPrixBl()) is None


def test_R21_avec_conversion_dunite() -> None:
    ligne = _ligne(
        prix_bon=Decimal("80.00"),
        unite_bon="seau",
        grille=_grille(prix=Decimal("100.00"), unite="kg"),
    )

    anomalie = R21(ligne, ParametresPrixBl())

    assert anomalie is not None
    assert anomalie.detail["unite_grille"] == "kg"
    assert anomalie.detail["ecart_pct"] == "-20.0"
