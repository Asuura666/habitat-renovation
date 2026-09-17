"""Tests de R07 — prix hors historique (CDC §5, L4-T4). Données
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
from app.modules.rules.rules.R07 import R07


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
        "pu_ht": Decimal("110.00"),
        "remise_pct": None,
        "montant_ht": Decimal("2200.00"),
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


def test_R07_ecart_moyen_produit_une_anomalie_moyenne() -> None:
    """PU 110 vs médiane 100 : écart de 10 %, dans (5 %, 15 %]."""
    article = _article(libelle="Ciment")
    ligne = _ligne(pu_ht=Decimal("110.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    anomalie = R07(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.regle == "R07"
    assert anomalie.gravite is Gravite.MOYENNE
    assert anomalie.ligne_id == ligne.id
    assert anomalie.article_id == article.id
    assert anomalie.bloc_id is None
    assert anomalie.document_id is None
    assert anomalie.detail == {
        "article": "Ciment",
        "code": "ART001",
        "pu_facture": "110.00",
        "mediane": "100.00",
        "occurrences": "3",
        "ecart_pct": "10.00",
    }
    assert anomalie.detail  # jamais vide


def test_R07_prix_inferieur_de_plus_de_5_pourcent_produit_une_anomalie() -> None:
    """L'écart est absolu : un prix inférieur à la médiane de plus de 5 %
    déclenche aussi R07 (CDC §5)."""
    article = _article()
    ligne = _ligne(pu_ht=Decimal("90.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    anomalie = R07(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.detail["ecart_pct"] == "10.00"


def test_R07_ecart_exactement_5_pourcent_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("105.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R07(ligne, article, historique, Parametres()) is None


def test_R07_ecart_exactement_15_pourcent_produit_une_anomalie() -> None:
    """La borne haute de R07 est incluse (`<=`) : à 15 % pile, c'est encore
    R07 (moyenne), pas R08 (matière du test d'exclusivité de R08)."""
    article = _article()
    ligne = _ligne(pu_ht=Decimal("115.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    anomalie = R07(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.gravite is Gravite.MOYENNE
    assert anomalie.detail["ecart_pct"] == "15.00"


def test_R07_ecart_au_dela_de_15_pourcent_ne_produit_rien() -> None:
    """Au-delà de 15 %, c'est R08, pas R07 (exclusivité)."""
    article = _article()
    ligne = _ligne(pu_ht=Decimal("120.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R07(ligne, article, historique, Parametres()) is None


def test_R07_moins_de_3_occurrences_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("110.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=2)

    assert R07(ligne, article, historique, Parametres()) is None


def test_R07_mediane_absente_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("110.00"))
    historique = _historique(mediane_pu=None, occurrences=10)

    assert R07(ligne, article, historique, Parametres()) is None


def test_R07_ligne_sans_pu_ht_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=None)
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R07(ligne, article, historique, Parametres()) is None


def test_R07_ligne_eco_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("110.00"), type_ligne="eco")
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R07(ligne, article, historique, Parametres()) is None


def test_R07_ligne_commentaire_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(pu_ht=Decimal("110.00"), type_ligne="commentaire")
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    assert R07(ligne, article, historique, Parametres()) is None


def test_R07_valeurs_manquantes_utilisent_un_tiret_et_la_designation() -> None:
    article = _article(libelle=None)
    ligne = _ligne(pu_ht=Decimal("110.00"), code=None, designation="DESIGNATION BRUTE")
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)

    anomalie = R07(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.detail["article"] == "DESIGNATION BRUTE"
    assert anomalie.detail["code"] == "—"


def test_R07_seuils_personnalises() -> None:
    """Les seuils sont ceux de `Parametres`, pas des constantes codées en
    dur : un seuil bas personnalisé (2 %) fait déclencher un écart de
    3 %."""
    article = _article()
    ligne = _ligne(pu_ht=Decimal("103.00"))
    historique = _historique(mediane_pu=Decimal("100.00"), occurrences=3)
    parametres = Parametres(
        seuil_prix_pct=Decimal("2"), seuil_prix_fort_pct=Decimal("15")
    )

    anomalie = R07(ligne, article, historique, parametres)

    assert anomalie is not None
    assert anomalie.detail["ecart_pct"] == "3.00"
