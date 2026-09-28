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
    commentaires,
    comptes,
    documents,
    factures,
    grilles,
    ia,
    journal,
    moi,
    parametres,
    prix,
    referentiels,
    tableau_de_bord,
)

router = APIRouter(prefix="/api")
router.include_router(moi.router)
router.include_router(factures.router)
router.include_router(documents.router)
router.include_router(a_traiter.router)
router.include_router(referentiels.router)
router.include_router(anomalies.router)
router.include_router(bilan.router)
router.include_router(journal.router)
router.include_router(parametres.router)
router.include_router(comptes.router)
router.include_router(tableau_de_bord.router)
router.include_router(commentaires.router)
router.include_router(grilles.router)
router.include_router(prix.router)
router.include_router(ia.router)

__all__ = ["router"]
