"""`GET /api/chantiers`, `POST /api/chantiers`, `GET /api/fournisseurs`,
`POST /api/alias-chantier/{id}/validation` et `POST /api/articles/{id}
/validation` (L3-T8b) : référentiels consommés par l'écran « À traiter » et
ses formulaires de validation — voir `ingest/referentiels.py` pour toute la
logique métier.

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`). Toutes
les routes sont réservées à l'admin (`admin_requis`) : un agent reçoit 403
avant tout accès au service.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import (
    ChantierCreationRequete,
    ChantierReponse,
    FournisseurReponse,
    ValidationAliasReponse,
    ValidationAliasRequete,
    ValidationArticleRequete,
)
from app.modules.ingest.referentiels import (
    AliasDejaValide,
    AliasIntrouvable,
    ArticleIntrouvable,
    ChantierEnDouble,
    ChantierIntrouvable,
    creer_chantier,
    lister_chantiers,
    lister_fournisseurs,
    valider_alias,
    valider_article,
)

router = APIRouter()


@router.get("/chantiers", response_model=list[ChantierReponse])
async def lister_chantiers_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ChantierReponse]:
    chantiers = await lister_chantiers(session)
    return [ChantierReponse.model_validate(chantier) for chantier in chantiers]


@router.post(
    "/chantiers",
    response_model=ChantierReponse,
    status_code=status.HTTP_201_CREATED,
)
async def creer_chantier_endpoint(
    requete: ChantierCreationRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChantierReponse | JSONResponse:
    try:
        chantier = await creer_chantier(
            session,
            nom_canonique=requete.nom_canonique,
            agence=requete.agence,
            auteur_id=utilisateur.id,
        )
    except ChantierEnDouble as exc:
        # Corps construit à la main (comme `NumeroDejaUtilise` dans
        # `api/documents.py`) : `original_id` doit apparaître au même niveau
        # que `detail`, pas imbriqué dessous.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "chantier déjà existant.",
                "original_id": str(exc.original_id),
            },
        )
    return ChantierReponse.model_validate(chantier)


@router.get("/fournisseurs", response_model=list[FournisseurReponse])
async def lister_fournisseurs_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[FournisseurReponse]:
    fournisseurs = await lister_fournisseurs(session)
    return [
        FournisseurReponse.model_validate(fournisseur) for fournisseur in fournisseurs
    ]


@router.post(
    "/alias-chantier/{alias_id}/validation", response_model=ValidationAliasReponse
)
async def valider_alias_endpoint(
    alias_id: uuid.UUID,
    requete: ValidationAliasRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ValidationAliasReponse:
    try:
        nb_mis_a_jour = await valider_alias(
            session,
            alias_id,
            chantier_id=requete.chantier_id,
            auteur_id=utilisateur.id,
        )
    except AliasIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="alias introuvable"
        ) from exc
    except ChantierIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="chantier introuvable"
        ) from exc
    except AliasDejaValide as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="alias déjà validé"
        ) from exc
    return ValidationAliasReponse(nb_mis_a_jour=nb_mis_a_jour)


@router.post(
    "/articles/{article_id}/validation", status_code=status.HTTP_204_NO_CONTENT
)
async def valider_article_endpoint(
    article_id: uuid.UUID,
    requete: ValidationArticleRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        await valider_article(
            session,
            article_id,
            unite_cdt=requete.unite_cdt,
            unite_fact=requete.unite_fact,
            ratio=requete.ratio,
            auteur_id=utilisateur.id,
        )
    except ArticleIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="article introuvable"
        ) from exc
