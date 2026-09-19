"""Routes administrateur de lecture et modification des seuils (L5-T10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import ModificationParametreRequete, ParametreReponse
from app.modules.ingest.parametres import lister_parametres, modifier_parametre

router = APIRouter()


@router.get("/parametres", response_model=list[ParametreReponse])
async def lister_parametres_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ParametreReponse]:
    del utilisateur
    parametres = await lister_parametres(session)
    return [ParametreReponse.model_validate(parametre) for parametre in parametres]


@router.put("/parametres/{cle}", response_model=ParametreReponse)
async def modifier_parametre_endpoint(
    cle: str,
    requete: ModificationParametreRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ParametreReponse:
    try:
        parametre = await modifier_parametre(
            session,
            cle,
            requete.valeur,
            auteur_id=utilisateur.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    await session.commit()
    return ParametreReponse.model_validate(parametre)
