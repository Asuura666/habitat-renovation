"""Tests de R04 — quantité facturée inférieure à la quantité BL (CDC §5,
L4-T3). Données inventées."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import (
    ArticleControle,
    BlocControle,
    Gravite,
    LigneControlee,
    LigneRapprochee,
)
from app.modules.rules.rules.R04 import R04


def _bloc(**overrides: Any) -> BlocControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_bl": "BL0001",
        "date_bl": None,
        "chantier_brut": "CHANTIER INVENTE",
        "chantier": "chantier invente",
        "commentaire": None,
        "montant_ht": Decimal("100.00"),
        "bl": None,
        "lignes": (),
        "lignes_bl_non_facturees": (),
        "autre_facture_numero": None,
        "autre_facture_id": None,
    }
    base.update(overrides)
    return BlocControle(**base)


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


def test_R04_ecart_negatif_produit_une_anomalie_moyenne() -> None:
    article_id = uuid.uuid4()
    article = _article(id=article_id, libelle="Ciment", unite_fact="kg")
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    ligne_facture = _ligne(article_id=article_id, qte_fact=Decimal("18"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc()

    anomalie = R04(bloc, rapprochee, {article_id: article})

    assert anomalie is not None
    assert anomalie.regle == "R04"
    assert anomalie.gravite is Gravite.MOYENNE
    assert anomalie.bloc_id == bloc.id
    assert anomalie.document_id is None
    assert anomalie.ligne_id == ligne_facture.id
    assert anomalie.article_id == article_id
    assert anomalie.detail == {
        "article": "Ciment",
        "code": "ART001",
        "qte_bl": "20",
        "qte_facture": "18",
        "unite": "kg",
        "ecart": "-2",
    }
    assert anomalie.detail  # jamais vide


def test_R04_ecart_positif_ne_produit_rien() -> None:
    """Matière de R03, pas de R04."""
    ligne_bl = _ligne(qte_fact=Decimal("18"))
    ligne_facture = _ligne(qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R04(_bloc(), rapprochee, {}) is None


def test_R04_egalite_exacte_ne_produit_rien() -> None:
    ligne_bl = _ligne(qte_fact=Decimal("20"))
    ligne_facture = _ligne(qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R04(_bloc(), rapprochee, {}) is None


def test_R04_ligne_non_appariee_ne_produit_rien() -> None:
    ligne_facture = _ligne(qte_fact=Decimal("18"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=None, methode=None)

    assert R04(_bloc(), rapprochee, {}) is None


def test_R04_conversion_impossible_cote_facture_ne_produit_rien() -> None:
    """CDC §10 : 0 anomalie R03/R04 due à une unité (L4-D7)."""
    ligne_bl = _ligne(qte_fact=Decimal("20"))
    ligne_facture = _ligne(qte_fact=None, conversion_impossible=True)
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R04(_bloc(), rapprochee, {}) is None


def test_R04_conversion_impossible_cote_bl_ne_produit_rien() -> None:
    ligne_bl = _ligne(qte_fact=None, conversion_impossible=True)
    ligne_facture = _ligne(qte_fact=Decimal("18"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R04(_bloc(), rapprochee, {}) is None


def test_R04_ligne_eco_ne_produit_rien() -> None:
    ligne_bl = _ligne(qte_fact=Decimal("20"), type_ligne="eco")
    ligne_facture = _ligne(qte_fact=Decimal("18"), type_ligne="eco")
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R04(_bloc(), rapprochee, {}) is None


def test_R04_ligne_bl_eco_alors_que_facture_est_un_article_ne_produit_rien() -> None:
    """Ruling R20 (revue finale du lot 4, Minor), symétrique de la même
    vérification côté R03 : le garde partagé (`ecart_qte_fact`) doit
    refuser la comparaison dès que l'une des deux lignes n'est pas de type
    "article", pas seulement la ligne de facture."""
    ligne_bl = _ligne(qte_fact=Decimal("20"), type_ligne="eco")
    ligne_facture = _ligne(qte_fact=Decimal("18"), type_ligne="article")
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R04(_bloc(), rapprochee, {}) is None


def test_R04_paire_unite_implicite_des_deux_cotes_produit_anomalie() -> None:
    """Ruling R16 (fix round 2, L4-T7) : non-régression, symétrique de la
    même vérification côté R03."""
    ligne_bl = _ligne(qte_fact=Decimal("20"), unite_implicite=True)
    ligne_facture = _ligne(qte_fact=Decimal("18"), unite_implicite=True)
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R04(_bloc(), rapprochee, {}) is not None


def test_R04_unite_implicite_vrai_cote_facture_seulement_ne_produit_rien() -> None:
    """Ruling R16 : paire mixte -> aucune comparaison, dans un sens."""
    ligne_bl = _ligne(qte_fact=Decimal("20"), unite_implicite=False)
    ligne_facture = _ligne(qte_fact=Decimal("18"), unite_implicite=True)
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R04(_bloc(), rapprochee, {}) is None


def test_R04_unite_implicite_vrai_cote_bl_seulement_ne_produit_rien() -> None:
    """Ruling R16 : paire mixte -> aucune comparaison, dans l'autre sens."""
    ligne_bl = _ligne(qte_fact=Decimal("20"), unite_implicite=True)
    ligne_facture = _ligne(qte_fact=Decimal("18"), unite_implicite=False)
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R04(_bloc(), rapprochee, {}) is None


def test_R04_article_inconnu_utilise_la_designation_et_un_tiret() -> None:
    ligne_bl = _ligne(article_id=None, qte_fact=Decimal("20"))
    ligne_facture = _ligne(
        article_id=None, designation="DESIGNATION BRUTE", qte_fact=Decimal("18")
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="libelle")

    anomalie = R04(_bloc(), rapprochee, {})

    assert anomalie is not None
    assert anomalie.detail["article"] == "DESIGNATION BRUTE"
    assert anomalie.detail["unite"] == "—"
    assert anomalie.article_id is None
