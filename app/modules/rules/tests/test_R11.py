"""Tests de R11 — incohérence arithmétique BL (CDC §5, L4-T1).

Même logique que R10 (L4-D8), appliquée à un BL rapproché : gravité
moyenne, `document_id` = le BL. Données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import DocumentControle, Gravite, Parametres
from app.modules.rules.rules.R11 import R11


def _bl(**overrides: Any) -> DocumentControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_interne": 1,
        "numero": "BL0001",
        "date_doc": date(2026, 8, 1),
        "statut": "recu",
        "somme_lignes": Decimal("50.00"),
        "total_ht": Decimal("50.00"),
        "ecart_somme": None,
        "depose_le": None,
        "deposant": None,
        "confirme_le": None,
    }
    base.update(overrides)
    return DocumentControle(**base)


def test_R11_sans_ecart_calcule_ne_produit_rien() -> None:
    bl = _bl(ecart_somme=None)
    assert R11(bl, Parametres()) is None


def test_R11_ecart_exactement_a_la_tolerance_ne_produit_rien() -> None:
    parametres = Parametres(tolerance_total_ht=Decimal("0.05"))
    bl = _bl(
        somme_lignes=Decimal("50.05"),
        total_ht=Decimal("50.00"),
        ecart_somme=Decimal("0.05"),
    )
    assert R11(bl, parametres) is None


def test_R11_ecart_au_dessus_de_la_tolerance_produit_une_anomalie_moyenne() -> None:
    parametres = Parametres(tolerance_total_ht=Decimal("0.05"))
    bl = _bl(
        somme_lignes=Decimal("50.10"),
        total_ht=Decimal("50.00"),
        ecart_somme=Decimal("0.10"),
    )

    anomalie = R11(bl, parametres)

    assert anomalie is not None
    assert anomalie.regle == "R11"
    assert anomalie.gravite is Gravite.MOYENNE
    assert anomalie.document_id == bl.id
    assert anomalie.bloc_id is None
    assert anomalie.ligne_id is None
    assert anomalie.detail == {
        "somme": "50.10",
        "total": "50.00",
        "ecart": "0.10",
        "tolerance": "0.05",
    }
    assert anomalie.detail  # jamais vide
