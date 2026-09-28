"""Tests de R19 — plus cher que la grille (phase 3, prix des bons). Données
inventées."""

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
from app.modules.rules.rules.R19 import R19

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
        "prix_bon": Decimal("7.90"),
        "unite_bon": "u",
        "date_bon": date(2026, 8, 1),
        "grille": _grille(),
        "candidats": (),
        "dernier_prix": None,
    }
    base.update(overrides)
    return LignePrixBl(**base)


def test_R19_positif_detail_complet() -> None:
    anomalie = R19(_ligne(), ParametresPrixBl())

    assert anomalie is not None
    assert anomalie.regle == "R19" and anomalie.gravite is Gravite.HAUTE
    assert anomalie.document_id == DOC and anomalie.ligne_id == LIGNE
    assert anomalie.article_id is None
    assert anomalie.detail == {
        "produit": "Plaque std 13",
        "code": "PLQ13",
        "prix_bon": "7.90",
        "unite_bon": "u",
        "date_bon": "2026-08-01",
        "prix_grille": "7.50",
        "unite_grille": "u",
        "date_grille": "2026-01-01",
        "ecart_pct": "5.3",
        "methode": "reference",
        "ressemblance": "100",
        "designation_grille": "Plaque std 13",
        "grille_posterieure_au_bon": "non",
    }


def test_R19_negatif_prix_egal_a_la_grille() -> None:
    assert R19(_ligne(prix_bon=Decimal("7.50")), ParametresPrixBl()) is None


def test_R19_limite_exacte_du_seuil_ne_declenche_rien() -> None:
    """Seuil de hausse 10 % : prix du bon exactement à la limite -> aucune
    anomalie (comparaison stricte, spec §5.2)."""
    parametres = ParametresPrixBl(seuil_hausse_pct=Decimal("10"))
    ligne = _ligne(prix_bon=Decimal("8.25"))  # 7.50 * 1.10 = 8.25

    assert R19(ligne, parametres) is None
    assert R19(_ligne(prix_bon=Decimal("8.26")), parametres) is not None


def test_R19_sans_grille_ne_declenche_rien() -> None:
    assert R19(_ligne(grille=None), ParametresPrixBl()) is None


def test_R19_reference_non_comparable_ne_declenche_rien() -> None:
    ligne = _ligne(
        prix_bon=Decimal("50.00"), grille=_grille(comparable=False, prix=Decimal("1"))
    )
    assert R19(ligne, ParametresPrixBl()) is None


def test_R19_avec_conversion_dunite() -> None:
    """Le prix de grille est déjà ramené à l'unité du bon par `ingest`
    (spec §4.4) : les deux unités affichées peuvent différer (grille au kg,
    bon au seau) sans empêcher la comparaison, tant que `comparable` est
    vrai."""
    ligne = _ligne(
        prix_bon=Decimal("120.00"),
        unite_bon="seau",
        grille=_grille(prix=Decimal("100.00"), unite="kg", comparable=True),
    )

    anomalie = R19(ligne, ParametresPrixBl())

    assert anomalie is not None
    assert anomalie.detail["unite_bon"] == "seau"
    assert anomalie.detail["unite_grille"] == "kg"
    assert anomalie.detail["ecart_pct"] == "20.0"


def test_R19_grille_posterieure_au_bon() -> None:
    ligne = _ligne(grille=_grille(grille_posterieure_au_bon=True))
    anomalie = R19(ligne, ParametresPrixBl())
    assert anomalie is not None
    assert anomalie.detail["grille_posterieure_au_bon"] == "oui"
