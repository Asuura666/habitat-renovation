"""`GET /api/commentaires/documents/{document_id}` et `POST
/api/commentaires/lignes/{ligne_id}` (tâche C2 de la phase 3, §5 de
`docs/superpowers/specs/2026-09-27-commentaires-lignes-design.md`) :
commentaires sur les lignes d'un bon (BL ou enlèvement) — voir
`ingest/commentaires.py` pour toute la logique métier.

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (jamais `extract`/`messaging` directement — garde
vérifiée par `tests/test_frontieres.py`). Les deux routes sont ouvertes à
tout compte connecté (`utilisateur_courant`), admin comme agent : un agent
ne voit et ne commente que les bons qu'il a déposés (décision d'Ilane du
27/09/2026, §6.3-8) — aucune règle ici, décision prise par
`ingest.commentaires`. `POST` passe par le contrôle d'origine existant
(`app.core.origine.ControleOrigineMiddleware`), comme toute écriture de
l'API.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, utilisateur_courant
from app.core.db import get_session
from app.modules.api.schemas import (
    CommentaireReponse,
    CommentaireRequete,
    CommentairesBonReponse,
)
from app.modules.ingest.commentaires import (
    CommentaireInvalide,
    LigneIntrouvable,
    ajouter_commentaire,
    commentaires_du_bon,
)
from app.modules.ingest.lecture import DocumentIntrouvable

router = APIRouter()


@router.get(
    "/commentaires/documents/{document_id}", response_model=CommentairesBonReponse
)
async def commentaires_du_bon_endpoint(
    document_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CommentairesBonReponse:
    try:
        commentaires = await commentaires_du_bon(
            session, document_id, utilisateur_id=utilisateur.id, role=utilisateur.role
        )
    except DocumentIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document introuvable"
        ) from exc
    return CommentairesBonReponse.model_validate(commentaires)


@router.post(
    "/commentaires/lignes/{ligne_id}",
    response_model=CommentaireReponse,
    status_code=status.HTTP_201_CREATED,
)
async def ajouter_commentaire_endpoint(
    ligne_id: uuid.UUID,
    requete: CommentaireRequete,
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CommentaireReponse:
    try:
        commentaire = await ajouter_commentaire(
            session,
            ligne_id,
            requete.texte,
            utilisateur_id=utilisateur.id,
            role=utilisateur.role,
        )
    except LigneIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ligne introuvable"
        ) from exc
    except CommentaireInvalide as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="commentaire invalide",
        ) from exc
    return CommentaireReponse.model_validate(commentaire)
