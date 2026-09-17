"""Tests de R16 — chantier silencieux (CDC §5, L4-T5). Données inventées."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from app.modules.rules.modeles import ChantierSuiviControle, Gravite, Parametres
from app.modules.rules.rules.R16 import R16

DERNIER_DEPOT = datetime(2026, 6, 1, 8, 0)


def _chantier(**overrides: Any) -> ChantierSuiviControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "nom": "Chantier Inventé",
        "dernier_depot": DERNIER_DEPOT,
        "nb_bl_factures_depuis": 1,
    }
    base.update(overrides)
    return ChantierSuiviControle(**base)


def test_R16_chantier_silencieux_avec_facture_produit_une_anomalie_basse() -> None:
    chantier = _chantier(nb_bl_factures_depuis=2)
    aujourdhui = DERNIER_DEPOT + timedelta(days=8)

    anomalie = R16(chantier, aujourdhui, Parametres())

    assert anomalie is not None
    assert anomalie.regle == "R16"
    assert anomalie.gravite is Gravite.BASSE
    assert anomalie.document_id is None
    assert anomalie.bloc_id is None
    assert anomalie.ligne_id is None
    assert anomalie.alias_id is None
    assert anomalie.chantier_id == chantier.id
    assert anomalie.detail == {
        "chantier": "Chantier Inventé",
        "dernier_depot": "2026-06-01T08:00:00",
        "bl_factures_depuis": "2",
        "jours": "8",
    }
    assert anomalie.detail  # jamais vide


def test_R16_deux_chantiers_distincts_portent_des_chantier_id_distincts() -> None:
    """Ruling du contrôleur (fix round 1) : sans `chantier_id`, deux
    chantiers silencieux distincts partageraient la même identité
    `("R16", None, None, None)` une fois persistés (L4-T11)."""
    chantier_1 = _chantier(nb_bl_factures_depuis=2)
    chantier_2 = _chantier(
        id=uuid.uuid4(), nom="Autre chantier", nb_bl_factures_depuis=1
    )
    aujourdhui = DERNIER_DEPOT + timedelta(days=8)

    anomalie_1 = R16(chantier_1, aujourdhui, Parametres())
    anomalie_2 = R16(chantier_2, aujourdhui, Parametres())

    assert anomalie_1 is not None
    assert anomalie_2 is not None
    assert anomalie_1.chantier_id == chantier_1.id
    assert anomalie_2.chantier_id == chantier_2.id
    assert anomalie_1.chantier_id != anomalie_2.chantier_id


def test_R16_exactement_au_delai_ne_produit_rien() -> None:
    chantier = _chantier()
    aujourdhui = DERNIER_DEPOT + timedelta(days=7)

    assert R16(chantier, aujourdhui, Parametres()) is None


def test_R16_avant_le_delai_ne_produit_rien() -> None:
    chantier = _chantier()
    aujourdhui = DERNIER_DEPOT + timedelta(days=1)

    assert R16(chantier, aujourdhui, Parametres()) is None


def test_R16_silencieux_sans_bl_facture_depuis_ne_produit_rien() -> None:
    """Le CDC exige « alors que des factures y référencent des BL » :
    aucun BL facturé depuis -> rien, même largement après le délai
    (décision du contrôleur)."""
    chantier = _chantier(nb_bl_factures_depuis=0)
    aujourdhui = DERNIER_DEPOT + timedelta(days=30)

    assert R16(chantier, aujourdhui, Parametres()) is None


def test_R16_sans_dernier_depot_ne_produit_rien() -> None:
    chantier = _chantier(dernier_depot=None)

    assert R16(chantier, datetime(2026, 12, 1), Parametres()) is None


def test_R16_delai_personnalise() -> None:
    parametres = Parametres(delai_chantier_silencieux_j=2)
    chantier = _chantier()
    aujourdhui = DERNIER_DEPOT + timedelta(days=3)

    assert R16(chantier, aujourdhui, parametres) is not None
