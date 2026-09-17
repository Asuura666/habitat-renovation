"""Tests de R08 — prix hors historique fort (CDC §5, L4-T4). Données
inventées."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import (
    ArticleControle,
    Gravite,
    HistoriqueArticle,
    LigneControlee,
    Parametres,
)
from app.modules.rules.rules.R08 import R08


def _ligne(**overrides: Any) -> LigneControlee:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ordre": 1,
        "code": "ART001",
        "designation": "ARTICLE INVENTE",
        "article_id": uuid.uuid4(),
        "qte_conditionnements": Decimal("2"),
        "qte_facturee": Decimal("20"),
        "qte_fact": Decimal("20"),
        "unite": "kg",
        "pu_ht": Decimal("130.00"),
        "remise_pct": None,
        "montant_ht": Decimal("2600.00"),
        "type_ligne": "article",
        "conversion_impossible": False,
    }
    base.update(overrides)
    return LigneControlee(**base)


def _article(**overrides: Any) -> ArticleControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "code": "ART001",
        "libelle": "Article inventé",
        "unite_cdt": "seau",
        "unite_fact": "kg",
        "ratio": Decimal("10"),
        "valide": True,
    }
    base.update(overrides)
    return ArticleControle(**base)


def _historique(**overrides: Any) -> HistoriqueArticle:
    base: dict[str, Any] = {
        "article_id": uuid.uuid4(),
        "mediane_pu": Decimal("100.00"),
        "occurrences": 3,
        "remise_habituelle": None,
        "occurrences_remise": 0,
    }
    base.update(overrides)
    return HistoriqueArticle(**base)


def test_R08_ecart_fort_produit_une_anomalie_haute() -> None:
    """PU 130 vs médiane 100 : écart de 30 %, strictement au-dessus de
    15 %."""
    article = _article(libelle="Ciment")
    ligne = _ligne(pu_ht=Decimal("130.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    anomalie = R08(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.regle == "R08"
    assert anomalie.gravite is Gravite.HAUTE
    assert anomalie.ligne_id == ligne.id
    assert anomalie.article_id == article.id
    assert anomalie.bloc_id is None
    assert anomalie.document_id is None
    assert anomalie.detail == {
        "article": "Ciment",
        "code": "ART001",
        "pu_facture": "130.00",
        "mediane": "100.00",
        "occurrences": "3",
        "ecart_pct": "30.00",
    }
    assert anomalie.detail  # jamais vide


def test_R08_prix_inferieur_de_plus_de_15_pourcent_produit_une_anomalie() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("80.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    anomalie = R08(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.detail["ecart_pct"] == "20.00"


def test_R08_ecart_exactement_15_pourcent_ne_produit_rien() -> None:
    """Borne haute de R07, pas de R08 (`>` strict)."""
    article = _article()
    ligne = _ligne(pu_ht=Decimal("115.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R08(ligne, article, historique, Parametres()) is None


def test_R08_ecart_sous_15_pourcent_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("110.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R08(ligne, article, historique, Parametres()) is None


def test_R08_moins_de_3_occurrences_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("130.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=2)

    assert R08(ligne, article, historique, Parametres()) is None


def test_R08_mediane_absente_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("130.00"))
    historique = _historique(mediane_pu=None, occurrences=10)

    assert R08(ligne, article, historique, Parametres()) is None


def test_R08_ligne_sans_pu_ht_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=None)
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R08(ligne, article, historique, Parametres()) is None


def test_R08_ligne_eco_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("130.00"), type_ligne="eco")
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R08(ligne, article, historique, Parametres()) is None


def test_R08_ligne_commentaire_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("130.00"), type_ligne="commentaire")
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R08(ligne, article, historique, Parametres()) is None


def test_R08_valeurs_manquantes_utilisent_un_tiret_et_la_designation() -> None:
    article = _article(libelle=None)
    ligne = _ligne(pu_ht=Decimal("130.00"), code=None, designation="DESIGNATION BRUTE")
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    anomalie = R08(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.detail["article"] == "DESIGNATION BRUTE"
    assert anomalie.detail["code"] == "—"
