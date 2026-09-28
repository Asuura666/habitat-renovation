"""Tests de R22 — produit absent de la grille (phase 3, prix des bons).
Données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import Gravite, LignePrixBl, ReferencePrix
from app.modules.rules.rules.R22 import R22

DOC = uuid.UUID(int=1)
LIGNE = uuid.UUID(int=2)


def _ligne(**overrides: Any) -> LignePrixBl:
    base: dict[str, Any] = {
        "document_id": DOC,
        "ligne_id": LIGNE,
        "designation": "Cloison std 70",
        "code": None,
        "prix_bon": Decimal("7.90"),
        "unite_bon": "u",
        "date_bon": date(2026, 8, 1),
        "grille": None,
        "candidats": (),
        "dernier_prix": None,
    }
    base.update(overrides)
    return LignePrixBl(**base)


def test_R22_positif_detail_complet() -> None:
    anomalie = R22(_ligne(candidats=("Cloison 48", "Cloison 90")))

    assert anomalie is not None
    assert anomalie.regle == "R22" and anomalie.gravite is Gravite.BASSE
    assert anomalie.document_id == DOC and anomalie.ligne_id == LIGNE
    assert anomalie.detail == {
        "produit": "Cloison std 70",
        "code": "—",
        "prix_bon": "7.90",
        "unite_bon": "u",
        "date_bon": "2026-08-01",
        "candidats": "Cloison 48 / Cloison 90",
    }


def test_R22_negatif_produit_trouve_dans_la_grille() -> None:
    grille = ReferencePrix(
        prix=Decimal("7.50"),
        unite="u",
        date=date(2026, 1, 1),
        comparable=True,
        methode="reference",
        ressemblance=100,
        designation="Cloison std 70",
        source="grille",
    )
    assert R22(_ligne(grille=grille)) is None


def test_R22_sans_candidats_tiret() -> None:
    anomalie = R22(_ligne())
    assert anomalie is not None
    assert anomalie.detail["candidats"] == "—"
