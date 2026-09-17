"""Tests de R15 — BL sans confirmation (CDC §5, L4-T5). Données inventées."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from app.modules.rules.modeles import DocumentControle, Gravite, Parametres
from app.modules.rules.rules.R15 import R15

DEPOSE_LE = datetime(2026, 6, 1, 8, 0)


def _document(**overrides: Any) -> DocumentControle:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "numero_interne": 1,
        "numero": None,
        "date_doc": date(2026, 6, 1),
        "statut": "extraite",
        "somme_lignes": None,
        "total_ht": None,
        "ecart_somme": None,
        "depose_le": DEPOSE_LE,
        "deposant": "Agent Un",
        "confirme_le": None,
    }
    base.update(overrides)
    return DocumentControle(**base)


def test_R15_bl_sans_confirmation_apres_le_delai_produit_une_anomalie_basse() -> None:
    document = _document(depose_le=DEPOSE_LE, deposant="Agent Un")
    aujourdhui = DEPOSE_LE + timedelta(hours=25)

    anomalie = R15(document, aujourdhui, Parametres())

    assert anomalie is not None
    assert anomalie.regle == "R15"
    assert anomalie.gravite is Gravite.BASSE
    assert anomalie.document_id == document.id
    assert anomalie.bloc_id is None
    assert anomalie.ligne_id is None
    assert anomalie.detail == {
        "deposant": "Agent Un",
        "depose_le": "2026-06-01T08:00:00",
        "heures": "25",
    }
    assert anomalie.detail  # jamais vide


def test_R15_exactement_au_delai_ne_produit_rien() -> None:
    document = _document()
    aujourdhui = DEPOSE_LE + timedelta(hours=24)

    assert R15(document, aujourdhui, Parametres()) is None


def test_R15_avant_le_delai_ne_produit_rien() -> None:
    document = _document()
    aujourdhui = DEPOSE_LE + timedelta(hours=1)

    assert R15(document, aujourdhui, Parametres()) is None


def test_R15_deja_confirme_ne_produit_rien() -> None:
    document = _document(confirme_le=datetime(2026, 6, 1, 9, 0))
    aujourdhui = DEPOSE_LE + timedelta(days=10)

    assert R15(document, aujourdhui, Parametres()) is None


def test_R15_sans_date_de_depot_ne_produit_rien() -> None:
    document = _document(depose_le=None)

    assert R15(document, datetime(2026, 12, 1), Parametres()) is None


def test_R15_deposant_absent_utilise_un_tiret() -> None:
    document = _document(deposant=None)
    aujourdhui = DEPOSE_LE + timedelta(hours=25)

    anomalie = R15(document, aujourdhui, Parametres())

    assert anomalie is not None
    assert anomalie.detail["deposant"] == "—"
