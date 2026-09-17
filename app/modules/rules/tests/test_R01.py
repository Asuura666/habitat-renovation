"""Tests de R01 — BL facturé non reçu (CDC §5, L4-T2). Données inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import BlocControle, DocumentControle, Gravite
from app.modules.rules.rules.R01 import R01


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
        "numero_bl": "L209900000123",
        "date_bl": date(2026, 8, 12),
        "chantier_brut": "MAISON TEST",
        "chantier": "maison test",
        "commentaire": None,
        "montant_ht": Decimal("245.30"),
        "bl": None,
        "lignes": (),
        "lignes_bl_non_facturees": (),
        "autre_facture_numero": None,
        "autre_facture_id": None,
    }
    base.update(overrides)
    return BlocControle(**base)


def test_R01_bloc_sans_bl_et_sans_mention_produit_une_anomalie_haute() -> None:
    bloc = _bloc()

    anomalie = R01(bloc)

    assert anomalie is not None
    assert anomalie.regle == "R01"
    assert anomalie.gravite is Gravite.HAUTE
    assert anomalie.bloc_id == bloc.id
    assert anomalie.document_id is None
    assert anomalie.ligne_id is None
    assert anomalie.detail == {
        "numero_bl": "L209900000123",
        "chantier": "maison test",
        "date_bl": "2026-08-12",
        "montant_ht": "245.30",
    }
    assert anomalie.detail  # jamais vide


def test_R01_bloc_avec_bl_rapproche_ne_produit_rien() -> None:
    bloc = _bloc(bl=_document())
    assert R01(bloc) is None


def test_R01_bloc_avec_bl_rapproche_et_mention_ne_produit_rien_non_plus() -> None:
    bloc = _bloc(bl=_document(), commentaire="RETRAIT FRED PAS DE BON")
    assert R01(bloc) is None


def test_R01_bloc_avec_mention_pas_de_bon_ne_produit_rien() -> None:
    """Matière de R02, pas de R01 : exclusivité (décision du contrôleur)."""
    bloc = _bloc(commentaire="RETRAIT FRED PAS DE BON")
    assert R01(bloc) is None


def test_R01_bloc_avec_mention_sans_bon_ne_produit_rien() -> None:
    bloc = _bloc(commentaire="CLIENT REPART SANS BON DE LIVRAISON")
    assert R01(bloc) is None


def test_R01_valeurs_manquantes_utilisent_un_tiret() -> None:
    bloc = _bloc(numero_bl=None, date_bl=None, chantier=None, chantier_brut=None)

    anomalie = R01(bloc)

    assert anomalie is not None
    assert anomalie.detail["numero_bl"] == "—"
    assert anomalie.detail["date_bl"] == "—"
    assert anomalie.detail["chantier"] == "—"


def test_R01_chantier_se_rabat_sur_le_brut_si_non_resolu() -> None:
    bloc = _bloc(chantier=None, chantier_brut="CHANTIER BRUT INVENTE")

    anomalie = R01(bloc)

    assert anomalie is not None
    assert anomalie.detail["chantier"] == "CHANTIER BRUT INVENTE"
