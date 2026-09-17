"""Tests de R09 — remise absente (CDC §5, L4-T4). Données inventées."""

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
from app.modules.rules.rules.R09 import R09


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
        "pu_ht": Decimal("100.00"),
        "remise_pct": None,
        "montant_ht": Decimal("2000.00"),
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
        "mediane_pu": None,
        "occurrences": 0,
        "remise_habituelle": Decimal("10.00"),
        "occurrences_remise": 3,
    }
    base.update(overrides)
    return HistoriqueArticle(**base)


def test_R09_remise_absente_produit_une_anomalie_moyenne() -> None:
    article = _article(libelle="Ciment")
    ligne = _ligne(remise_pct=None)
    historique = _historique(remise_habituelle=Decimal("10.00"), occurrences_remise=3)

    anomalie = R09(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.regle == "R09"
    assert anomalie.gravite is Gravite.MOYENNE
    assert anomalie.ligne_id == ligne.id
    assert anomalie.article_id == article.id
    assert anomalie.bloc_id is None
    assert anomalie.document_id is None
    assert anomalie.detail == {
        "article": "Ciment",
        "code": "ART001",
        "remise_habituelle": "10.00",
        "remise_appliquee": "—",
        "occurrences": "3",
    }
    assert anomalie.detail  # jamais vide


def test_R09_remise_nulle_produit_une_anomalie() -> None:
    """`remise_pct` égale à zéro compte comme « sans remise » (décision du
    contrôleur), avec sa valeur affichée dans le detail (pas un tiret)."""
    article = _article()
    ligne = _ligne(remise_pct=Decimal("0"))
    historique = _historique(remise_habituelle=Decimal("10.00"), occurrences_remise=3)

    anomalie = R09(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.detail["remise_appliquee"] == "0"


def test_R09_remise_plus_faible_que_lhabituelle_ne_produit_rien() -> None:
    """Le CDC ne parle que de l'absence : une remise plus faible que
    l'habituelle n'est pas R09 (décision du contrôleur)."""
    article = _article()
    ligne = _ligne(remise_pct=Decimal("5.00"))
    historique = _historique(remise_habituelle=Decimal("10.00"), occurrences_remise=3)

    assert R09(ligne, article, historique, Parametres()) is None


def test_R09_remise_appliquee_egale_a_lhabituelle_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(remise_pct=Decimal("10.00"))
    historique = _historique(remise_habituelle=Decimal("10.00"), occurrences_remise=3)

    assert R09(ligne, article, historique, Parametres()) is None


def test_R09_moins_de_3_occurrences_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(remise_pct=None)
    historique = _historique(remise_habituelle=Decimal("10.00"), occurrences_remise=2)

    assert R09(ligne, article, historique, Parametres()) is None


def test_R09_remise_habituelle_absente_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(remise_pct=None)
    historique = _historique(remise_habituelle=None, occurrences_remise=10)

    assert R09(ligne, article, historique, Parametres()) is None


def test_R09_ligne_eco_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(remise_pct=None, type_ligne="eco")
    historique = _historique(remise_habituelle=Decimal("10.00"), occurrences_remise=3)

    assert R09(ligne, article, historique, Parametres()) is None


def test_R09_ligne_commentaire_ne_produit_rien() -> None:
    article = _article()
    ligne = _ligne(remise_pct=None, type_ligne="commentaire")
    historique = _historique(remise_habituelle=Decimal("10.00"), occurrences_remise=3)

    assert R09(ligne, article, historique, Parametres()) is None


def test_R09_valeurs_manquantes_utilisent_un_tiret_et_la_designation() -> None:
    article = _article(libelle=None)
    ligne = _ligne(remise_pct=None, code=None, designation="DESIGNATION BRUTE")
    historique = _historique(remise_habituelle=Decimal("10.00"), occurrences_remise=3)

    anomalie = R09(ligne, article, historique, Parametres())

    assert anomalie is not None
    assert anomalie.detail["article"] == "DESIGNATION BRUTE"
    assert anomalie.detail["code"] == "—"


def test_R09_occurrences_prix_min_personnalise() -> None:
    """Le seuil d'occurrences est celui de `Parametres`
    (`occurrences_prix_min`), pas une constante codée en dur."""
    article = _article()
    ligne = _ligne(remise_pct=None)
    historique = _historique(remise_habituelle=Decimal("10.00"), occurrences_remise=5)
    parametres = Parametres(occurrences_prix_min=6)

    assert R09(ligne, article, historique, parametres) is None
