"""Tests de R13 — avoir sans origine (CDC §5, L4-T5). Données inventées."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import Gravite, LigneControlee
from app.modules.rules.rules.R13 import R13


def _ligne(**overrides: Any) -> LigneControlee:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ordre": 1,
        "code": "ART001",
        "designation": "ARTICLE INVENTE",
        "article_id": uuid.uuid4(),
        "qte_conditionnements": Decimal("-2"),
        "qte_facturee": Decimal("-20"),
        "qte_fact": Decimal("-20"),
        "unite": "kg",
        "pu_ht": Decimal("100.00"),
        "remise_pct": None,
        "montant_ht": Decimal("-2000.00"),
        "type_ligne": "article",
        "conversion_impossible": False,
    }
    base.update(overrides)
    return LigneControlee(**base)


def test_R13_ligne_negative_sans_origine_produit_une_anomalie_moyenne() -> None:
    ligne = _ligne(designation="Ciment", code="CIM01", montant_ht=Decimal("-150.00"))

    anomalie = R13(ligne, "Chantier Inventé")

    assert anomalie is not None
    assert anomalie.regle == "R13"
    assert anomalie.gravite is Gravite.MOYENNE
    assert anomalie.ligne_id == ligne.id
    assert anomalie.article_id == ligne.article_id
    assert anomalie.bloc_id is None
    assert anomalie.document_id is None
    assert anomalie.detail == {
        "article": "Ciment",
        "code": "CIM01",
        "montant": "-150.00",
        "chantier": "Chantier Inventé",
    }
    assert anomalie.detail  # jamais vide


def test_R13_chantier_absent_utilise_un_tiret() -> None:
    ligne = _ligne()

    anomalie = R13(ligne, None)

    assert anomalie is not None
    assert anomalie.detail["chantier"] == "—"


def test_R13_ligne_eco_ne_produit_rien() -> None:
    ligne = _ligne(type_ligne="eco")

    assert R13(ligne, "Chantier") is None


def test_R13_ligne_commentaire_ne_produit_rien() -> None:
    ligne = _ligne(type_ligne="commentaire")

    assert R13(ligne, "Chantier") is None


def test_R13_valeurs_manquantes_utilisent_un_tiret_et_la_designation() -> None:
    ligne = _ligne(code=None, designation="DESIGNATION BRUTE", montant_ht=None)

    anomalie = R13(ligne, "Chantier")

    assert anomalie is not None
    assert anomalie.detail["article"] == "DESIGNATION BRUTE"
    assert anomalie.detail["code"] == "—"
    assert anomalie.detail["montant"] == "—"
