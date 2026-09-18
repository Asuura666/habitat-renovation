"""Tests de R03 — quantité facturée supérieure à la quantité BL (CDC §5,
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
from app.modules.rules.rules.R03 import R03


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


def test_R03_ecart_positif_produit_une_anomalie_haute() -> None:
    article_id = uuid.uuid4()
    article = _article(id=article_id, libelle="Ciment", unite_fact="kg")
    ligne_bl = _ligne(article_id=article_id, qte_fact=Decimal("18"))
    ligne_facture = _ligne(article_id=article_id, qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")
    bloc = _bloc()

    anomalie = R03(bloc, rapprochee, {article_id: article})

    assert anomalie is not None
    assert anomalie.regle == "R03"
    assert anomalie.gravite is Gravite.HAUTE
    assert anomalie.bloc_id == bloc.id
    assert anomalie.document_id is None
    assert anomalie.ligne_id == ligne_facture.id
    assert anomalie.article_id == article_id
    assert anomalie.detail == {
        "article": "Ciment",
        "code": "ART001",
        "qte_bl": "18",
        "qte_facture": "20",
        "unite": "kg",
        "ecart": "2",
    }
    assert anomalie.detail  # jamais vide


def test_R03_ecart_negatif_ne_produit_rien() -> None:
    """Matière de R04, pas de R03."""
    ligne_bl = _ligne(qte_fact=Decimal("20"))
    ligne_facture = _ligne(qte_fact=Decimal("18"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_egalite_exacte_ne_produit_rien() -> None:
    ligne_bl = _ligne(qte_fact=Decimal("20"))
    ligne_facture = _ligne(qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_ligne_non_appariee_ne_produit_rien() -> None:
    ligne_facture = _ligne(qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=None, methode=None)

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_conversion_impossible_cote_facture_ne_produit_rien() -> None:
    """CDC §10 : 0 anomalie R03/R04 due à une unité (L4-D7)."""
    ligne_bl = _ligne(qte_fact=Decimal("18"))
    ligne_facture = _ligne(qte_fact=None, conversion_impossible=True)
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_conversion_impossible_cote_bl_ne_produit_rien() -> None:
    ligne_bl = _ligne(qte_fact=None, conversion_impossible=True)
    ligne_facture = _ligne(qte_fact=Decimal("20"))
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_ligne_eco_ne_produit_rien() -> None:
    ligne_bl = _ligne(qte_fact=Decimal("18"), type_ligne="eco")
    ligne_facture = _ligne(qte_fact=Decimal("20"), type_ligne="eco")
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_ligne_commentaire_ne_produit_rien() -> None:
    ligne_bl = _ligne(qte_fact=Decimal("18"), type_ligne="commentaire")
    ligne_facture = _ligne(qte_fact=Decimal("20"), type_ligne="commentaire")
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_ligne_bl_eco_alors_que_facture_est_un_article_ne_produit_rien() -> None:
    """Ruling R20 (revue finale du lot 4, Minor) : le garde doit être
    symétrique. Avant le correctif, seul `facture.type_ligne` était vérifié
    -- une ligne de facture "article" appariée (même code) à une ligne de
    BL "eco" produisait un écart chiffré entre deux grandeurs qui n'ont
    rien à voir."""
    ligne_bl = _ligne(qte_fact=Decimal("18"), type_ligne="eco")
    ligne_facture = _ligne(qte_fact=Decimal("20"), type_ligne="article")
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_ligne_bl_commentaire_alors_que_facture_est_article() -> None:
    """Même garde, avec une ligne de BL "commentaire" plutôt que "eco"."""
    ligne_bl = _ligne(qte_fact=Decimal("18"), type_ligne="commentaire")
    ligne_facture = _ligne(qte_fact=Decimal("20"), type_ligne="article")
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_paire_unite_implicite_des_deux_cotes_produit_anomalie() -> None:
    """Ruling R16 (fix round 2, L4-T7) : deux lignes en cas 2 (unité connue
    nulle part) des deux côtés restent comparables entre elles --
    non-régression du gain du Ruling R14."""
    ligne_bl = _ligne(qte_fact=Decimal("18"), unite_implicite=True)
    ligne_facture = _ligne(qte_fact=Decimal("20"), unite_implicite=True)
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is not None


def test_R03_unite_implicite_vrai_cote_facture_seulement_ne_produit_rien() -> None:
    """Ruling R16 : une paire mixte (une seule ligne en unité implicite) ne
    doit jamais produire de comparaison -- comparerait deux unités
    potentiellement différentes."""
    ligne_bl = _ligne(qte_fact=Decimal("18"), unite_implicite=False)
    ligne_facture = _ligne(qte_fact=Decimal("20"), unite_implicite=True)
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_unite_implicite_vrai_cote_bl_seulement_ne_produit_rien() -> None:
    """Même garde, dans l'autre sens."""
    ligne_bl = _ligne(qte_fact=Decimal("18"), unite_implicite=True)
    ligne_facture = _ligne(qte_fact=Decimal("20"), unite_implicite=False)
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R03(_bloc(), rapprochee, {}) is None


def test_R03_article_inconnu_utilise_la_designation_et_un_tiret() -> None:
    ligne_bl = _ligne(article_id=None, qte_fact=Decimal("18"))
    ligne_facture = _ligne(
        article_id=None, designation="DESIGNATION BRUTE", qte_fact=Decimal("20")
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="libelle")

    anomalie = R03(_bloc(), rapprochee, {})

    assert anomalie is not None
    assert anomalie.detail["article"] == "DESIGNATION BRUTE"
    assert anomalie.detail["unite"] == "—"
    assert anomalie.article_id is None
