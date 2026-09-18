"""Agrégateur des routeurs JSON consommés par le front (`/api/...`).

Couche d'entrée (L2-D3) : chaque sous-module de `api` n'importe que
`app.core` et, s'il a besoin d'orchestrer une action métier, `ingest`
(jamais `extract`/`normalize`/`rules`/`messaging` directement — garde
vérifiée par `tests/test_frontieres.py`). Le préfixe `/api` est posé une
seule fois ici ; chaque sous-module expose un `router` sans préfixe.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.api import (
    a_traiter,
    anomalies,
    bilan,
    documents,
    factures,
    moi,
    referentiels,
)

router = APIRouter(prefix="/api")
router.include_router(moi.router)
router.include_router(factures.router)
router.include_router(documents.router)
router.include_router(a_traiter.router)
router.include_router(referentiels.router)
router.include_router(anomalies.router)
router.include_router(bilan.router)

__all__ = ["router"]
