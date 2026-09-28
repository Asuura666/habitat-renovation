"""Tests de R24 — unités différentes (phase 3, prix des bons). Données
inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import Gravite, LignePrixBl, ReferencePrix
from app.modules.rules.rules.R24 import R24

DOC = uuid.UUID(int=1)
LIGNE = uuid.UUID(int=2)


def _reference(**overrides: Any) -> ReferencePrix:
    base: dict[str, Any] = {
        "prix": Decimal("7.50"),
        "unite": "kg",
        "date": date(2026, 1, 1),
        "comparable": False,
        "methode": "reference",
        "ressemblance": 100,
        "designation": "Enduit E2",
        "source": "grille",
    }
    base.update(overrides)
    return ReferencePrix(**base)


def _ligne(**overrides: Any) -> LignePrixBl:
    base: dict[str, Any] = {
        "document_id": DOC,
        "ligne_id": LIGNE,
        "designation": "Enduit E2",
        "code": None,
        "prix_bon": Decimal("7.90"),
        "unite_bon": "sac",
        "date_bon": date(2026, 8, 1),
        "grille": _reference(),
        "candidats": (),
        "dernier_prix": None,
    }
    base.update(overrides)
    return LignePrixBl(**base)


def test_R24_positif_grille_non_comparable() -> None:
    anomalie = R24(_ligne())

    assert anomalie is not None
    assert anomalie.regle == "R24" and anomalie.gravite is Gravite.MOYENNE
    assert anomalie.document_id == DOC and anomalie.ligne_id == LIGNE
    assert anomalie.detail == {
        "produit": "Enduit E2",
        "code": "—",
        "unite_bon": "sac",
        "unite_grille": "kg",
        "unite_dernier_prix": "—",
        "prix_bon": "7.90",
    }


def test_R24_positif_dernier_prix_non_comparable() -> None:
    ligne = _ligne(
        grille=None,
        dernier_prix=_reference(unite="rouleau", source="facture"),
    )
    anomalie = R24(ligne)
    assert anomalie is not None
    assert anomalie.detail["unite_grille"] == "—"
    assert anomalie.detail["unite_dernier_prix"] == "rouleau"


def test_R24_positif_les_deux_non_comparables() -> None:
    ligne = _ligne(
        dernier_prix=_reference(unite="rouleau", source="facture"),
    )
    anomalie = R24(ligne)
    assert anomalie is not None
    assert anomalie.detail["unite_grille"] == "kg"
    assert anomalie.detail["unite_dernier_prix"] == "rouleau"


def test_R24_positif_grille_comparable_dernier_prix_non_comparable() -> None:
    """Constat qualité (tour 1) : quand la grille est comparable, son unité
    ne doit pas apparaître dans le détail même si la grille est présente --
    seule l'unité de la référence réellement non comparable (ici la
    dernière facture) doit figurer."""
    ligne = _ligne(
        grille=_reference(comparable=True),
        dernier_prix=_reference(unite="rouleau", source="facture"),
    )
    anomalie = R24(ligne)
    assert anomalie is not None
    assert anomalie.detail["unite_grille"] == "—"
    assert anomalie.detail["unite_dernier_prix"] == "rouleau"


def test_R24_negatif_les_deux_comparables() -> None:
    ligne = _ligne(
        grille=_reference(comparable=True),
        dernier_prix=_reference(comparable=True, source="facture"),
    )
    assert R24(ligne) is None


def test_R24_negatif_ni_grille_ni_dernier_prix() -> None:
    assert R24(_ligne(grille=None, dernier_prix=None)) is None
