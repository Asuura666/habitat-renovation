"""`GET /api/a-traiter` (L3-T8b) : écran « À traiter » de l'admin — documents
« à vérifier » (BL, enlèvements et factures), alias chantier en attente de
validation, articles à valider.

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`). Toute
la requête SQL vit dans `ingest.a_traiter.lister_a_traiter` — ce routeur ne
fait que l'appeler et sérialiser. Réservé à l'admin (`admin_requis`, L3-D18) :
un agent reçoit 403.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import ATraiterReponse
from app.modules.ingest.a_traiter import lister_a_traiter

router = APIRouter()


@router.get("/a-traiter", response_model=ATraiterReponse)
async def obtenir_a_traiter(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ATraiterReponse:
    a_traiter = await lister_a_traiter(session)
    return ATraiterReponse.model_validate(a_traiter)
