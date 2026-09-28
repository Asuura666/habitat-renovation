"""Tests de R20 — plus cher que la dernière fois (phase 3, prix des bons).
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
from app.modules.rules.rules.R20 import R20

DOC = uuid.UUID(int=1)
LIGNE = uuid.UUID(int=2)


def _dernier_prix(**overrides: Any) -> ReferencePrix:
    base: dict[str, Any] = {
        "prix": Decimal("7.20"),
        "unite": "u",
        "date": date(2026, 6, 12),
        "comparable": True,
        "methode": "reference",
        "ressemblance": 100,
        "designation": "Plaque std 13",
        "source": "facture",
        "numero_facture": "F123",
    }
    base.update(overrides)
    return ReferencePrix(**base)


def _ligne(**overrides: Any) -> LignePrixBl:
    base: dict[str, Any] = {
        "document_id": DOC,
        "ligne_id": LIGNE,
        "designation": "Plaque std 13",
        "code": "PLQ13",
        "prix_bon": Decimal("7.90"),
        "unite_bon": "u",
        "date_bon": date(2026, 8, 1),
        "grille": None,
        "candidats": (),
        "dernier_prix": _dernier_prix(),
    }
    base.update(overrides)
    return LignePrixBl(**base)


def test_R20_positif_detail_complet() -> None:
    anomalie = R20(_ligne(), ParametresPrixBl())

    assert anomalie is not None
    assert anomalie.regle == "R20" and anomalie.gravite is Gravite.HAUTE
    assert anomalie.document_id == DOC and anomalie.ligne_id == LIGNE
    assert anomalie.article_id is None
    assert anomalie.detail == {
        "produit": "Plaque std 13",
        "code": "PLQ13",
        "prix_bon": "7.90",
        "unite_bon": "u",
        "date_bon": "2026-08-01",
        "dernier_prix": "7.20",
        "unite_dernier_prix": "u",
        "date_dernier_prix": "2026-06-12",
        "numero_facture": "F123",
        "ecart_pct": "9.7",
        "methode": "reference",
        "ressemblance": "100",
    }


def test_R20_negatif_prix_egal() -> None:
    assert R20(_ligne(prix_bon=Decimal("7.20")), ParametresPrixBl()) is None


def test_R20_limite_exacte_du_seuil_ne_declenche_rien() -> None:
    parametres = ParametresPrixBl(seuil_hausse_pct=Decimal("10"))
    ligne = _ligne(prix_bon=Decimal("7.92"))  # 7.20 * 1.10 = 7.92

    assert R20(ligne, parametres) is None
    assert R20(_ligne(prix_bon=Decimal("7.93")), parametres) is not None


def test_R20_sans_dernier_prix_ne_declenche_rien() -> None:
    assert R20(_ligne(dernier_prix=None), ParametresPrixBl()) is None


def test_R20_reference_non_comparable_ne_declenche_rien() -> None:
    ligne = _ligne(
        prix_bon=Decimal("50.00"),
        dernier_prix=_dernier_prix(comparable=False, prix=Decimal("1")),
    )
    assert R20(ligne, ParametresPrixBl()) is None


def test_R20_avec_conversion_dunite() -> None:
    ligne = _ligne(
        prix_bon=Decimal("120.00"),
        unite_bon="seau",
        dernier_prix=_dernier_prix(prix=Decimal("100.00"), unite="kg"),
    )

    anomalie = R20(ligne, ParametresPrixBl())

    assert anomalie is not None
    assert anomalie.detail["unite_dernier_prix"] == "kg"
    assert anomalie.detail["ecart_pct"] == "20.0"
