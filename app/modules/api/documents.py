"""`GET /api/documents` et `GET /api/documents/{id}/fichier` (L2-T5) :
lecture des BL et enlèvements.

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (jamais `extract`/`messaging` directement — garde
vérifiée par `tests/test_frontieres.py`). Ouvert aux deux rôles
(`utilisateur_courant`) : le CDC réserve les factures à l'admin, pas les BL —
`ingest.lecture.lister_documents`/`fichier_document` décident seuls de ce
que chaque rôle voit (aucune règle ici, décision du contrôleur).

`limite` (`1..500`, défaut 100) est une borne de requête HTTP, pas une règle
métier : elle est validée ici par FastAPI (`Query(ge=..., le=...)`), comme la
taille maximale du fichier dans `factures.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, utilisateur_courant
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.modules.api.schemas import DocumentReponse
from app.modules.ingest.lecture import (
    LIMITE_DOCUMENTS_DEFAUT,
    LIMITE_DOCUMENTS_MAX,
    LIMITE_DOCUMENTS_MIN,
    DocumentIntrouvable,
    fichier_document,
    lister_documents,
)

router = APIRouter()


@router.get("/documents", response_model=list[DocumentReponse])
async def lister_documents_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    session: Annotated[AsyncSession, Depends(get_session)],
    depuis: Annotated[datetime | None, Query()] = None,
    limite: Annotated[
        int, Query(ge=LIMITE_DOCUMENTS_MIN, le=LIMITE_DOCUMENTS_MAX)
    ] = LIMITE_DOCUMENTS_DEFAUT,
) -> list[DocumentReponse]:
    resumes = await lister_documents(
        session,
        utilisateur_id=utilisateur.id,
        role=utilisateur.role,
        depuis=depuis,
        limite=limite,
    )
    return [DocumentReponse.model_validate(resume) for resume in resumes]


@router.get("/documents/{document_id}/fichier")
async def telecharger_document(
    document_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    try:
        fichier = await fichier_document(
            session,
            document_id,
            settings.docs_dir,
            utilisateur_id=utilisateur.id,
            role=utilisateur.role,
        )
    except DocumentIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="document introuvable"
        ) from exc
    return FileResponse(fichier.chemin, media_type=fichier.type_mime)
