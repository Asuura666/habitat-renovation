"""Tests de R06 — ligne BL non facturée (CDC §5, L4-T5). Données inventées."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import BlocControle, Gravite, LigneControlee, Parametres
from app.modules.rules.rules.R06 import R06


def _bloc(**overrides: Any) -> BlocControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_bl": "BL0001",
        "date_bl": date(2026, 6, 1),
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


def test_R06_ligne_bl_non_facturee_apres_le_delai_produit_une_anomalie_basse() -> None:
    date_bl = date(2026, 6, 1)
    bloc = _bloc(date_bl=date_bl)
    ligne = _ligne(designation="Ciment", code="CIM01", qte_facturee=Decimal("10"))
    aujourdhui = datetime.combine(date_bl + timedelta(days=46), datetime.min.time())

    anomalie = R06(bloc, ligne, aujourdhui, Parametres())

    assert anomalie is not None
    assert anomalie.regle == "R06"
    assert anomalie.gravite is Gravite.BASSE
    assert anomalie.bloc_id == bloc.id
    assert anomalie.ligne_id == ligne.id
    assert anomalie.article_id == ligne.article_id
    assert anomalie.document_id is None
    assert anomalie.detail == {
        "article": "Ciment",
        "code": "CIM01",
        "qte": "10",
        "date_bl": "2026-06-01",
        "jours": "46",
    }
    assert anomalie.detail  # jamais vide


def test_R06_exactement_au_delai_ne_produit_rien() -> None:
    date_bl = date(2026, 6, 1)
    bloc = _bloc(date_bl=date_bl)
    ligne = _ligne()
    aujourdhui = datetime.combine(date_bl + timedelta(days=45), datetime.min.time())

    assert R06(bloc, ligne, aujourdhui, Parametres()) is None


def test_R06_avant_le_delai_ne_produit_rien() -> None:
    date_bl = date(2026, 6, 1)
    bloc = _bloc(date_bl=date_bl)
    ligne = _ligne()
    aujourdhui = datetime.combine(date_bl + timedelta(days=10), datetime.min.time())

    assert R06(bloc, ligne, aujourdhui, Parametres()) is None


def test_R06_ligne_eco_ne_produit_rien() -> None:
    date_bl = date(2026, 6, 1)
    bloc = _bloc(date_bl=date_bl)
    ligne = _ligne(type_ligne="eco")
    aujourdhui = datetime.combine(date_bl + timedelta(days=100), datetime.min.time())

    assert R06(bloc, ligne, aujourdhui, Parametres()) is None


def test_R06_bloc_sans_date_bl_ne_produit_rien() -> None:
    bloc = _bloc(date_bl=None)
    ligne = _ligne()

    assert R06(bloc, ligne, datetime(2026, 12, 1), Parametres()) is None


def test_R06_delai_personnalise() -> None:
    parametres = Parametres(delai_ligne_bl_non_facturee_j=10)
    date_bl = date(2026, 6, 1)
    bloc = _bloc(date_bl=date_bl)
    ligne = _ligne()
    aujourdhui = datetime.combine(date_bl + timedelta(days=11), datetime.min.time())

    assert R06(bloc, ligne, aujourdhui, parametres) is not None


def test_R06_valeurs_manquantes_utilisent_un_tiret() -> None:
    date_bl = date(2026, 6, 1)
    bloc = _bloc(date_bl=date_bl)
    ligne = _ligne(code=None, designation=None, qte_facturee=None)
    aujourdhui = datetime.combine(date_bl + timedelta(days=100), datetime.min.time())

    anomalie = R06(bloc, ligne, aujourdhui, Parametres())

    assert anomalie is not None
    assert anomalie.detail["article"] == "—"
    assert anomalie.detail["code"] == "—"
    assert anomalie.detail["qte"] == "—"
