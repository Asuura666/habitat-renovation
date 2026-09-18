"""`GET /api/anomalies` et `POST /api/anomalies/{id}/traitement` (L4-T9) :
liste filtrable et cycle de vie des anomalies — voir `ingest/anomalies.py`
(L4-T8, commité, non modifié ici) pour toute la logique métier.

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`).
Réservé à l'admin (`admin_requis`, Q3 du brief lot 4) : un agent reçoit 403
avant tout accès au service.

Filtres de `GET /api/anomalies` (décision du contrôleur) : `regle`,
`gravite`, `statut` (défaut `ouverte`), `chantier_id`, `fournisseur_id`,
`depuis`/`jusqu_a` (sur `created_at`), `limite` (1..500, défaut 100) —
combinables, validés ici par FastAPI (`Literal`, `Query(ge=..., le=...)`),
jamais par le service (même principe que `limite` dans `api/documents.py`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import AnomalieReponse, TraitementAnomalieRequete
from app.modules.ingest.anomalies import (
    LIMITE_ANOMALIES_DEFAUT,
    AnomalieIntrouvable,
    TransitionInterdite,
    lister_anomalies,
    traiter_anomalie,
)

router = APIRouter()

_LIMITE_MIN = 1
_LIMITE_MAX = 500


@router.get("/anomalies", response_model=list[AnomalieReponse])
async def lister_anomalies_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    regle: Annotated[str | None, Query()] = None,
    gravite: Annotated[Literal["haute", "moyenne", "basse"] | None, Query()] = None,
    statut: Annotated[
        Literal["ouverte", "traitee", "ignoree"] | None, Query()
    ] = "ouverte",
    chantier_id: Annotated[uuid.UUID | None, Query()] = None,
    fournisseur_id: Annotated[uuid.UUID | None, Query()] = None,
    depuis: Annotated[datetime | None, Query()] = None,
    jusqu_a: Annotated[datetime | None, Query()] = None,
    limite: Annotated[
        int, Query(ge=_LIMITE_MIN, le=_LIMITE_MAX)
    ] = LIMITE_ANOMALIES_DEFAUT,
) -> list[AnomalieReponse]:
    anomalies = await lister_anomalies(
        session,
        regle=regle,
        gravite=gravite,
        statut=statut,
        chantier_id=chantier_id,
        fournisseur_id=fournisseur_id,
        depuis=depuis,
        jusqu_a=jusqu_a,
        limite=limite,
    )
    return [AnomalieReponse.model_validate(anomalie) for anomalie in anomalies]


@router.post("/anomalies/{anomalie_id}/traitement", response_model=AnomalieReponse)
async def traiter_anomalie_endpoint(
    anomalie_id: uuid.UUID,
    requete: TraitementAnomalieRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnomalieReponse:
    try:
        anomalie = await traiter_anomalie(
            session,
            anomalie_id,
            statut=requete.statut,
            commentaire=requete.commentaire,
            auteur_id=utilisateur.id,
        )
    except AnomalieIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="anomalie introuvable"
        ) from exc
    except TransitionInterdite as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="transition interdite"
        ) from exc
    return AnomalieReponse.model_validate(anomalie)
