"""Tests de R25 — grille ancienne (phase 3, prix des bons). Données
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
from app.modules.rules.rules.R25 import R25

DOC = uuid.UUID(int=1)
LIGNE = uuid.UUID(int=2)


def _grille(**overrides: Any) -> ReferencePrix:
    base: dict[str, Any] = {
        "prix": Decimal("7.50"),
        "unite": "u",
        "date": date(2025, 1, 1),
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
        "code": None,
        "prix_bon": Decimal("7.90"),
        "unite_bon": "u",
        "date_bon": date(2026, 9, 1),
        "grille": _grille(),
        "candidats": (),
        "dernier_prix": None,
    }
    base.update(overrides)
    return LignePrixBl(**base)


def test_R25_positif_detail_complet() -> None:
    parametres = ParametresPrixBl(aujourdhui=date(2026, 9, 1))
    anomalie = R25(_ligne(), parametres)

    assert anomalie is not None
    assert anomalie.regle == "R25" and anomalie.gravite is Gravite.BASSE
    assert anomalie.document_id == DOC and anomalie.ligne_id == LIGNE
    assert anomalie.detail == {
        "produit": "Plaque std 13",
        "code": "—",
        "date_grille": "2025-01-01",
        "age_mois": "20",
        "prix_grille": "7.50",
    }


def test_R25_negatif_grille_recente() -> None:
    ligne = _ligne(grille=_grille(date=date(2026, 8, 1)))
    assert R25(ligne, ParametresPrixBl(aujourdhui=date(2026, 9, 1))) is None


def test_R25_limite_exacte_de_lage_ne_declenche_rien() -> None:
    """`age_grille_mois` par défaut : 12. Exactement 12 mois -> rien ; un
    mois de plus -> l'anomalie (comparaison stricte, spec §5.2)."""
    ligne_12_mois_pile = _ligne(grille=_grille(date=date(2025, 9, 1)))
    ligne_13_mois = _ligne(grille=_grille(date=date(2025, 8, 1)))
    parametres = ParametresPrixBl(aujourdhui=date(2026, 9, 1))

    assert R25(ligne_12_mois_pile, parametres) is None
    anomalie = R25(ligne_13_mois, parametres)
    assert anomalie is not None
    assert anomalie.detail["age_mois"] == "13"


def test_R25_calcul_des_mois_fin_de_mois() -> None:
    """Une grille du 31 janvier, contrôlée le 28 février : le mois n'est
    pas encore plein (28 < 31) -- `mois_ecoules` corrige d'un mois plutôt
    que de compter un mois calendaire naïf (0 mois écoulé, pas 1)."""
    ligne = _ligne(grille=_grille(date=date(2026, 1, 31)))
    parametres = ParametresPrixBl(age_grille_mois=1, aujourdhui=date(2026, 2, 28))

    assert R25(ligne, parametres) is None

    parametres_au_dela = ParametresPrixBl(
        age_grille_mois=1, aujourdhui=date(2026, 4, 1)
    )
    anomalie = R25(ligne, parametres_au_dela)
    assert anomalie is not None
    assert anomalie.detail["age_mois"] == "2"


def test_R25_sans_grille_ne_declenche_rien() -> None:
    parametres = ParametresPrixBl(aujourdhui=date(2026, 9, 1))
    assert R25(_ligne(grille=None), parametres) is None


def test_R25_reference_non_comparable_ne_declenche_rien() -> None:
    ligne = _ligne(grille=_grille(comparable=False, date=date(2000, 1, 1)))
    assert R25(ligne, ParametresPrixBl(aujourdhui=date(2026, 9, 1))) is None


def test_R25_sans_aujourdhui_ne_declenche_rien() -> None:
    ligne = _ligne(grille=_grille(date=date(2000, 1, 1)))
    assert R25(ligne, ParametresPrixBl()) is None
