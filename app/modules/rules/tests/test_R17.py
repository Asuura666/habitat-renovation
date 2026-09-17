"""Tests de R17 — conditionnement inhabituel (CDC §5, L4-T3). Données
inventées."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import ArticleControle, Gravite, LigneControlee
from app.modules.rules.rules.R17 import R17


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
        "pu_ht": Decimal("1.50"),
        "remise_pct": None,
        "montant_ht": Decimal("30.00"),
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


def test_R17_quantite_decimale_produit_une_anomalie_moyenne() -> None:
    article = _article(libelle="Peinture", unite_cdt="seau", ratio=Decimal("10"))
    ligne = _ligne(qte_conditionnements=Decimal("2.5"), code="ART001")

    anomalie = R17(ligne, article)

    assert anomalie is not None
    assert anomalie.regle == "R17"
    assert anomalie.gravite is Gravite.MOYENNE
    assert anomalie.bloc_id is None
    assert anomalie.document_id is None
    assert anomalie.ligne_id == ligne.id
    assert anomalie.article_id == article.id
    assert anomalie.detail == {
        "article": "Peinture",
        "code": "ART001",
        "qte": "2.5",
        "conditionnement": "seau",
        "ratio": "10",
    }
    assert anomalie.detail  # jamais vide


def test_R17_quantite_entiere_ne_produit_rien() -> None:
    article = _article(ratio=Decimal("10"))
    ligne = _ligne(qte_conditionnements=Decimal("2"))

    assert R17(ligne, article) is None


def test_R17_quantite_entiere_avec_zeros_decimaux_ne_produit_rien() -> None:
    article = _article(ratio=Decimal("10"))
    ligne = _ligne(qte_conditionnements=Decimal("3.00"))

    assert R17(ligne, article) is None


def test_R17_quantite_absente_ne_produit_rien() -> None:
    article = _article(ratio=Decimal("10"))
    ligne = _ligne(qte_conditionnements=None)

    assert R17(ligne, article) is None


def test_R17_ratio_absent_ne_produit_rien() -> None:
    article = _article(ratio=None)
    ligne = _ligne(qte_conditionnements=Decimal("2.5"))

    assert R17(ligne, article) is None


def test_R17_ratio_nul_ne_produit_rien() -> None:
    article = _article(ratio=Decimal("0"))
    ligne = _ligne(qte_conditionnements=Decimal("2.5"))

    assert R17(ligne, article) is None


def test_R17_article_non_valide_ne_produit_rien() -> None:
    article = _article(ratio=Decimal("10"), valide=False)
    ligne = _ligne(qte_conditionnements=Decimal("2.5"))

    assert R17(ligne, article) is None


def test_R17_ligne_eco_ne_produit_rien() -> None:
    article = _article(ratio=Decimal("10"))
    ligne = _ligne(qte_conditionnements=Decimal("2.5"), type_ligne="eco")

    assert R17(ligne, article) is None


def test_R17_ligne_commentaire_ne_produit_rien() -> None:
    article = _article(ratio=Decimal("10"))
    ligne = _ligne(qte_conditionnements=Decimal("2.5"), type_ligne="commentaire")

    assert R17(ligne, article) is None


def test_R17_valeurs_manquantes_utilisent_un_tiret_et_la_designation() -> None:
    article = _article(libelle=None, unite_cdt=None, ratio=Decimal("10"))
    ligne = _ligne(qte_conditionnements=Decimal("2.5"), designation="DESIGNATION BRUTE")

    anomalie = R17(ligne, article)

    assert anomalie is not None
    assert anomalie.detail["article"] == "DESIGNATION BRUTE"
    assert anomalie.detail["conditionnement"] == "—"
