"""`GET/POST /api/comptes`, `PUT /api/comptes/{id}`, `PUT /api/comptes/{id}
/mot-de-passe`, `POST /api/comptes/{id}/retirer-acces` et `POST /api
/comptes/{id}/retablir-acces` (Task 10, spec §3) : écran « Comptes »
(admin seulement), accessible depuis Réglages -- toute la logique
métier (validation, unicité, garde-fous, journal) vit dans `app.core.auth`
(seul module autorisé à écrire `Utilisateur`, L2-D4) ; ce routeur valide le
corps de requête, appelle le service, traduit ses exceptions en réponse
HTTP, sérialise.

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` (garde vérifiée
par `tests/test_frontieres.py`) -- pas `ingest`, contrairement aux autres
routeurs de `api` : la gestion des comptes vit entièrement dans
`app.core.auth`, jamais dans `ingest` (L2-D4).

Toutes les routes sont réservées à l'admin (`admin_requis`) : un agent
reçoit 403 avant tout accès au service.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    ActionSurSoiInterdite,
    DernierAdmin,
    EmailDejaUtilise,
    MotDePasseTropCourt,
    RoleInvalide,
    TelegramUserIdDejaAttribue,
    Utilisateur,
    UtilisateurIntrouvable,
    admin_requis,
    changer_mot_de_passe,
    creer_compte,
    lister_comptes,
    modifier_compte,
    retablir_acces,
    retirer_acces,
)
from app.core.db import get_session
from app.modules.api.schemas import (
    ChangementMotDePasseRequete,
    CompteCreationRequete,
    CompteModificationRequete,
    CompteReponse,
)

router = APIRouter()


@router.get("/comptes", response_model=list[CompteReponse])
async def lister_comptes_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CompteReponse]:
    del utilisateur
    comptes = await lister_comptes(session)
    return [CompteReponse.model_validate(compte) for compte in comptes]


@router.post(
    "/comptes", response_model=CompteReponse, status_code=status.HTTP_201_CREATED
)
async def creer_compte_endpoint(
    requete: CompteCreationRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CompteReponse:
    try:
        compte = await creer_compte(
            session,
            email=requete.email,
            nom=requete.nom,
            role=requete.role,
            agence=requete.agence,
            telegram_user_id=requete.telegram_user_id,
            mot_de_passe=requete.mot_de_passe,
            auteur_id=utilisateur.id,
        )
    except (RoleInvalide, MotDePasseTropCourt) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except (EmailDejaUtilise, TelegramUserIdDejaAttribue) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return CompteReponse.model_validate(compte)


@router.put("/comptes/{compte_id}", response_model=CompteReponse)
async def modifier_compte_endpoint(
    compte_id: uuid.UUID,
    requete: CompteModificationRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CompteReponse:
    try:
        compte = await modifier_compte(
            session,
            compte_id,
            email=requete.email,
            nom=requete.nom,
            role=requete.role,
            agence=requete.agence,
            telegram_user_id=requete.telegram_user_id,
            auteur_id=utilisateur.id,
        )
    except UtilisateurIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="compte introuvable"
        ) from exc
    except RoleInvalide as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except (EmailDejaUtilise, TelegramUserIdDejaAttribue) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except DernierAdmin as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return CompteReponse.model_validate(compte)


@router.put("/comptes/{compte_id}/mot-de-passe", status_code=status.HTTP_204_NO_CONTENT)
async def changer_mot_de_passe_endpoint(
    compte_id: uuid.UUID,
    requete: ChangementMotDePasseRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    try:
        await changer_mot_de_passe(
            session,
            compte_id,
            mot_de_passe=requete.mot_de_passe,
            auteur_id=utilisateur.id,
        )
    except UtilisateurIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="compte introuvable"
        ) from exc
    except MotDePasseTropCourt as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post("/comptes/{compte_id}/retirer-acces", response_model=CompteReponse)
async def retirer_acces_endpoint(
    compte_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CompteReponse:
    try:
        compte = await retirer_acces(session, compte_id, auteur_id=utilisateur.id)
    except UtilisateurIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="compte introuvable"
        ) from exc
    except ActionSurSoiInterdite as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except DernierAdmin as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return CompteReponse.model_validate(compte)


@router.post("/comptes/{compte_id}/retablir-acces", response_model=CompteReponse)
async def retablir_acces_endpoint(
    compte_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CompteReponse:
    try:
        compte = await retablir_acces(session, compte_id, auteur_id=utilisateur.id)
    except UtilisateurIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="compte introuvable"
        ) from exc
    return CompteReponse.model_validate(compte)
