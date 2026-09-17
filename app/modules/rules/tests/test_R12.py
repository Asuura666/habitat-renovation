"""Tests de R12 — doublon de facturation (CDC §5, L4-T2). Données
inventées."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.rules.modeles import BlocControle, DocumentControle, Gravite
from app.modules.rules.rules.R12 import R12


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


def test_R12_sans_doublon_ne_produit_rien() -> None:
    bloc = _bloc()
    assert R12(bloc, "FAC-2026-001") is None


def test_R12_doublon_produit_une_anomalie_haute() -> None:
    autre_facture_id = uuid.uuid4()
    bloc = _bloc(autre_facture_numero="FAC-2026-000", autre_facture_id=autre_facture_id)

    anomalie = R12(bloc, "FAC-2026-001")

    assert anomalie is not None
    assert anomalie.regle == "R12"
    assert anomalie.gravite is Gravite.HAUTE
    assert anomalie.bloc_id == bloc.id
    assert anomalie.document_id is None
    assert anomalie.ligne_id is None
    assert anomalie.detail == {
        "numero_bl": "L209900000123",
        "facture": "FAC-2026-001",
        "autre_facture": "FAC-2026-000",
        "montant_ht": "245.30",
    }
    assert anomalie.detail  # jamais vide


def test_R12_est_independant_du_bl_rapproche() -> None:
    """R12 se déclenche même si le bloc a par ailleurs un BL rapproché
    (`bl` non `None`) : le doublon de facturation est un sujet distinct du
    rapprochement bloc <-> BL (R01/R02)."""
    bl = DocumentControle(
        id=uuid.uuid4(),
        numero_interne=1,
        numero="L209900000123",
        date_doc=date(2026, 8, 12),
        statut="recu",
        somme_lignes=Decimal("245.30"),
        total_ht=Decimal("245.30"),
        ecart_somme=None,
        depose_le=None,
        deposant=None,
        confirme_le=None,
    )
    bloc = _bloc(
        bl=bl, autre_facture_numero="FAC-2026-000", autre_facture_id=uuid.uuid4()
    )

    anomalie = R12(bloc, "FAC-2026-001")

    assert anomalie is not None
    assert anomalie.regle == "R12"


def test_R12_valeurs_manquantes_utilisent_un_tiret() -> None:
    bloc = _bloc(
        numero_bl=None, autre_facture_numero=None, autre_facture_id=uuid.uuid4()
    )

    anomalie = R12(bloc, None)

    assert anomalie is not None
    assert anomalie.detail["numero_bl"] == "—"
    assert anomalie.detail["facture"] == "—"
    assert anomalie.detail["autre_facture"] == "—"
