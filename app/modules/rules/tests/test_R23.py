"""Tests de R23 — produit reconnu seulement par son nom (phase 3, prix des
bons). Données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import Gravite, LignePrixBl, ReferencePrix
from app.modules.rules.rules.R23 import R23

DOC = uuid.UUID(int=1)
LIGNE = uuid.UUID(int=2)


def _grille(**overrides: Any) -> ReferencePrix:
    base: dict[str, Any] = {
        "prix": Decimal("7.50"),
        "unite": "u",
        "date": date(2026, 1, 1),
        "comparable": True,
        "methode": "nom",
        "ressemblance": 83,
        "designation": "Plaque std 13",
        "source": "grille",
    }
    base.update(overrides)
    return ReferencePrix(**base)


def _ligne(**overrides: Any) -> LignePrixBl:
    base: dict[str, Any] = {
        "document_id": DOC,
        "ligne_id": LIGNE,
        "designation": "PLAQUE STANDARD BA13 2.5M",
        "code": None,
        "prix_bon": Decimal("7.90"),
        "unite_bon": "u",
        "date_bon": date(2026, 8, 1),
        "grille": _grille(),
        "candidats": (),
        "dernier_prix": None,
    }
    base.update(overrides)
    return LignePrixBl(**base)


def test_R23_positif_detail_complet() -> None:
    anomalie = R23(_ligne())

    assert anomalie is not None
    assert anomalie.regle == "R23" and anomalie.gravite is Gravite.BASSE
    assert anomalie.document_id == DOC and anomalie.ligne_id == LIGNE
    assert anomalie.detail == {
        "produit": "PLAQUE STANDARD BA13 2.5M",
        "code": "—",
        "designation_grille": "Plaque std 13",
        "ressemblance": "83",
        "prix_bon": "7.90",
        "prix_grille": "7.50",
    }


def test_R23_negatif_reconnu_par_reference() -> None:
    assert R23(_ligne(grille=_grille(methode="reference"))) is None


def test_R23_sans_grille_ne_declenche_rien() -> None:
    assert R23(_ligne(grille=None)) is None


def test_R23_reference_non_comparable_ne_declenche_rien() -> None:
    """Spec §5.2 : une référence non comparable n'alimente que R24."""
    assert R23(_ligne(grille=_grille(comparable=False))) is None
