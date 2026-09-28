"""`GET /api/ia/synthese`, `POST /api/ia/synthese/actions/{action_id}/faite`
et `POST /api/ia/synthese/actions/{action_id}/a-faire` (T4, phase 4 IA, spec
§4.6) : carte « Commentaires de la semaine » de la Vue d'ensemble (T5
construira l'écran) — toute la logique métier (sélection, cochage,
journal) vit dans `ingest.ia_synthese` ; ce routeur valide, appelle le
service, sérialise.

`GET /api/ia/anomalies/{anomalie_id}` (T6, phase 4 IA, spec §6.4) : avis de
l'IA (explication de l'alerte, prix trouvé sur internet) pour l'encart
`AvisIA.tsx` du détail d'un problème (T7 construira l'écran) — même
principe, toute la logique vit dans `ingest.ia_prix.avis_ia_anomalie`.

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (jamais `extract` directement — garde vérifiée par
`tests/test_frontieres.py`). Les quatre routes sont réservées à l'admin
(`admin_requis`, même principe qu'`api/comptes.py`) : la synthèse résume des
commentaires (donc, indirectement, des chantiers) et l'avis IA porte sur une
anomalie de prix, deux données qu'un simple agent ne voit normalement qu'au
compte-goutte (`ingest.commentaires`, un bon à la fois ; l'écran « À
régler ») — jamais agrégées ou expliquées par l'IA comme ici."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import (
    ActionSyntheseReponse,
    AvisIAReponse,
    SyntheseAccueilReponse,
)
from app.modules.ingest.anomalies import AnomalieIntrouvable
from app.modules.ingest.ia_prix import avis_ia_anomalie
from app.modules.ingest.ia_synthese import (
    ActionIntrouvable,
    marquer_action,
    vue_accueil,
)

router = APIRouter()


@router.get("/ia/synthese", response_model=SyntheseAccueilReponse)
async def synthese_accueil_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SyntheseAccueilReponse:
    del utilisateur
    accueil = await vue_accueil(session)
    return SyntheseAccueilReponse.model_validate(accueil)


async def _marquer_action_endpoint(
    session: AsyncSession,
    action_id: uuid.UUID,
    *,
    faite: bool,
    utilisateur: Utilisateur,
) -> ActionSyntheseReponse:
    """Commun aux deux routes ci-dessous (seul `faite` change) : évite de
    dupliquer la traduction `ActionIntrouvable` -> 404."""
    try:
        action = await marquer_action(
            session, action_id, faite=faite, utilisateur_id=utilisateur.id
        )
    except ActionIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="action introuvable"
        ) from exc
    return ActionSyntheseReponse.model_validate(action)


@router.post(
    "/ia/synthese/actions/{action_id}/faite", response_model=ActionSyntheseReponse
)
async def marquer_action_faite_endpoint(
    action_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActionSyntheseReponse:
    return await _marquer_action_endpoint(
        session, action_id, faite=True, utilisateur=utilisateur
    )


@router.post(
    "/ia/synthese/actions/{action_id}/a-faire", response_model=ActionSyntheseReponse
)
async def marquer_action_a_faire_endpoint(
    action_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ActionSyntheseReponse:
    return await _marquer_action_endpoint(
        session, action_id, faite=False, utilisateur=utilisateur
    )


@router.get("/ia/anomalies/{anomalie_id}", response_model=AvisIAReponse)
async def avis_ia_anomalie_endpoint(
    anomalie_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AvisIAReponse:
    del utilisateur
    try:
        avis = await avis_ia_anomalie(session, anomalie_id)
    except AnomalieIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="anomalie introuvable"
        ) from exc
    return AvisIAReponse.model_validate(avis)
