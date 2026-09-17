"""`GET /api/moi` : identité de l'utilisateur courant (L2-T1).

N'importe que `app.core` (décision du contrôleur pour L2-T1) : la
dépendance d'authentification et le type `Utilisateur` viennent de
`app.core.auth` (seul endroit autorisé, par L2-D4, à importer
`ingest.models`). Le schéma de réponse est local à ce fichier :
`app/modules/api/schemas.py` n'existe pas encore (prévu en L2-T5).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import Utilisateur, utilisateur_courant

router = APIRouter()


class MoiReponse(BaseModel):
    id: uuid.UUID
    email: str
    nom: str | None
    role: str
    agence: str | None


@router.get("/moi", response_model=MoiReponse)
async def moi(
    utilisateur: Annotated[Utilisateur, Depends(utilisateur_courant)],
) -> MoiReponse:
    return MoiReponse(
        id=utilisateur.id,
        email=utilisateur.email,
        nom=utilisateur.nom,
        role=utilisateur.role,
        agence=utilisateur.agence,
    )
