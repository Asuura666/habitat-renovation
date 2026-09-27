"""Tests de R18 — chantier à confirmer (avenant du 27/09/2026). Données
inventées."""

from __future__ import annotations

import uuid

from app.modules.rules.modeles import ChantierIncertainControle, Gravite
from app.modules.rules.rules.R18 import R18

DOC = uuid.UUID(int=10)
A, B = uuid.UUID(int=1), uuid.UUID(int=2)


def _controle(incertain: bool) -> ChantierIncertainControle:
    return ChantierIncertainControle(
        document_id=DOC,
        nom_lu="VILLA TEST",
        legende="tilleuls",
        candidats=("Villa Test", "Résidence des Tilleuls"),
        candidats_ids=(A, B),
        incertain=incertain,
    )


def test_R18_positif_detail_complet() -> None:
    anomalie = R18(_controle(True))
    assert anomalie is not None
    assert anomalie.regle == "R18" and anomalie.gravite is Gravite.MOYENNE
    assert anomalie.document_id == DOC
    assert anomalie.detail == {
        "nom_lu": "VILLA TEST",
        "legende": "tilleuls",
        "candidats": "Villa Test / Résidence des Tilleuls",
        "candidats_ids": f"{A},{B}",
    }


def test_R18_negatif_chantier_certain() -> None:
    assert R18(_controle(False)) is None


def test_R18_valeurs_absentes_en_tiret() -> None:
    c = ChantierIncertainControle(
        document_id=DOC,
        nom_lu=None,
        legende=None,
        candidats=("A", "B"),
        candidats_ids=(A, B),
        incertain=True,
    )
    anomalie = R18(c)
    assert (
        anomalie is not None
        and anomalie.detail["nom_lu"] == "—"
        and anomalie.detail["legende"] == "—"
    )
