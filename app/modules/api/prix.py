"""`GET /api/prix/alertes` et `POST /api/prix/valider`, `/contester`,
`/ignorer`, `/recontrole` (phase 3, tâche P8, spec
`docs/superpowers/specs/2026-09-27-prix-design.md` §8.2, §10) : la page
« Prix à vérifier » -- voir `ingest/prix_bl.py` (tâche P7 puis P8) pour toute
la logique métier (regroupement par produit, actions).

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`). Toutes
les routes sont réservées à l'admin (`admin_requis`, spec §9 : « Admin
seulement ») : ni la page Prix ni ses actions ne regardent l'agent de
terrain.

Aucune règle métier ici : ce routeur valide, appelle `ingest.prix_bl`,
sérialise -- le regroupement par produit, la correspondance de grille et le
recontrôle après validation vivent tous dans `ingest/prix_bl.py`."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import (
    AlerteProduitReponse,
    ContesterPrixRequete,
    FermetureAlertesReponse,
    IgnorerPrixRequete,
    RecontrolePrixReponse,
    ValidationPrixReponse,
    ValiderPrixRequete,
)
from app.modules.ingest.prix_bl import (
    AlertesInvalides,
    contester_prix,
    ignorer_prix,
    lister_alertes_prix,
    recontroler_depuis_page,
    valider_prix,
)

router = APIRouter()


def _erreur_alertes_invalides(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _erreur_commentaire(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
    )


@router.get("/prix/alertes", response_model=list[AlerteProduitReponse])
async def lister_alertes_prix_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    periode: Annotated[Literal["jour", "tout"], Query()] = "tout",
    fournisseur_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[AlerteProduitReponse]:
    del utilisateur
    produits = await lister_alertes_prix(
        session, periode=periode, fournisseur_id=fournisseur_id
    )
    return [AlerteProduitReponse.model_validate(produit) for produit in produits]


@router.post("/prix/valider", response_model=ValidationPrixReponse)
async def valider_prix_endpoint(
    requete: ValiderPrixRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ValidationPrixReponse:
    try:
        resultat = await valider_prix(
            session,
            anomalie_ids=requete.anomalie_ids,
            ligne_id=requete.ligne_id,
            auteur_id=utilisateur.id,
        )
    except AlertesInvalides as exc:
        raise _erreur_alertes_invalides(exc) from exc
    return ValidationPrixReponse.model_validate(resultat)


@router.post("/prix/contester", response_model=FermetureAlertesReponse)
async def contester_prix_endpoint(
    requete: ContesterPrixRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FermetureAlertesReponse:
    try:
        nb = await contester_prix(
            session,
            anomalie_ids=requete.anomalie_ids,
            commentaire=requete.commentaire,
            auteur_id=utilisateur.id,
        )
    except AlertesInvalides as exc:
        raise _erreur_alertes_invalides(exc) from exc
    except ValueError as exc:
        raise _erreur_commentaire(exc) from exc
    return FermetureAlertesReponse(nb_alertes_reglees=nb)


@router.post("/prix/ignorer", response_model=FermetureAlertesReponse)
async def ignorer_prix_endpoint(
    requete: IgnorerPrixRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FermetureAlertesReponse:
    try:
        nb = await ignorer_prix(
            session,
            anomalie_ids=requete.anomalie_ids,
            commentaire=requete.commentaire,
            auteur_id=utilisateur.id,
        )
    except AlertesInvalides as exc:
        raise _erreur_alertes_invalides(exc) from exc
    except ValueError as exc:
        raise _erreur_commentaire(exc) from exc
    return FermetureAlertesReponse(nb_alertes_reglees=nb)


@router.post("/prix/recontrole", response_model=RecontrolePrixReponse)
async def recontroler_prix_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RecontrolePrixReponse:
    resultat = await recontroler_depuis_page(session, auteur_id=utilisateur.id)
    return RecontrolePrixReponse.model_validate(resultat)
