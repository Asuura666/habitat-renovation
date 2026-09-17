"""Tests de R05 — ligne facturée absente du BL (CDC §5, L4-T3). Données
inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import (
    BlocControle,
    DocumentControle,
    Gravite,
    LigneControlee,
    LigneRapprochee,
)
from app.modules.rules.rules.R05 import R05


def _document(**overrides: Any) -> DocumentControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_interne": 1,
        "numero": "L209900000123",
        "date_doc": date(2026, 8, 12),
        "statut": "recu",
        "somme_lignes": Decimal("245.30"),
        "total_ht": Decimal("245.30"),
        "ecart_somme": None,
        "depose_le": None,
        "deposant": None,
        "confirme_le": None,
    }
    base.update(overrides)
    return DocumentControle(**base)


def _bloc(**overrides: Any) -> BlocControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_bl": "BL0001",
        "date_bl": None,
        "chantier_brut": "CHANTIER INVENTE",
        "chantier": "chantier invente",
        "commentaire": None,
        "montant_ht": Decimal("100.00"),
        "bl": _document(),
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


def test_R05_ligne_non_appariee_avec_bl_rapproche_produit_une_anomalie_haute() -> None:
    ligne_facture = _ligne(
        designation="CIMENT 25KG", code="ART001", qte_facturee=Decimal("20")
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=None, methode=None)
    bloc = _bloc()

    anomalie = R05(bloc, rapprochee)

    assert anomalie is not None
    assert anomalie.regle == "R05"
    assert anomalie.gravite is Gravite.HAUTE
    assert anomalie.bloc_id == bloc.id
    assert anomalie.document_id is None
    assert anomalie.ligne_id == ligne_facture.id
    assert anomalie.article_id == ligne_facture.article_id
    assert anomalie.detail == {
        "article": "CIMENT 25KG",
        "code": "ART001",
        "qte": "20",
        "montant": "30.00",
    }
    assert anomalie.detail  # jamais vide


def test_R05_ligne_appariee_ne_produit_rien() -> None:
    ligne_bl = _ligne()
    ligne_facture = _ligne()
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=ligne_bl, methode="code")

    assert R05(_bloc(), rapprochee) is None


def test_R05_bloc_sans_bl_rapproche_ne_produit_rien() -> None:
    """Matière de R01/R02 (BL non reçu), pas de R05."""
    ligne_facture = _ligne()
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=None, methode=None)

    assert R05(_bloc(bl=None), rapprochee) is None


def test_R05_ligne_eco_ne_produit_rien() -> None:
    ligne_facture = _ligne(type_ligne="eco")
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=None, methode=None)

    assert R05(_bloc(), rapprochee) is None


def test_R05_ligne_commentaire_ne_produit_rien() -> None:
    ligne_facture = _ligne(type_ligne="commentaire")
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=None, methode=None)

    assert R05(_bloc(), rapprochee) is None


def test_R05_valeurs_manquantes_utilisent_un_tiret() -> None:
    ligne_facture = _ligne(
        designation=None, code=None, qte_facturee=None, montant_ht=None
    )
    rapprochee = LigneRapprochee(facture=ligne_facture, bl=None, methode=None)

    anomalie = R05(_bloc(), rapprochee)

    assert anomalie is not None
    assert anomalie.detail == {
        "article": "—",
        "code": "—",
        "qte": "—",
        "montant": "—",
    }
