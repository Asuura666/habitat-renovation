"""`GET /api/chantiers`, `POST /api/chantiers`, `PUT /api/chantiers/{id}`
(client du chantier et modification, ajout hors CDC du 23/09/2026,
`docs/dette.md`), `GET /api/chantiers/{id}` (fiche, y compris un chantier
fusionné) et `POST /api/chantiers/{id}/fusionner` (« Fusionner avec… »,
Task 7, avenant du 27/09/2026, spec §2.7), `GET /api/fournisseurs`, `POST
/api/alias-chantier/{id}/validation` et `POST /api/articles/{id}/validation`
(L3-T8b) : référentiels consommés par l'écran « À traiter » et ses
formulaires de validation — voir `ingest/referentiels.py` (et `ingest
/fusion_chantier.py` pour la fusion) pour toute la logique métier.

`GET /api/referentiels/depots-par-agent`, `GET /api/referentiels
/chantiers-silencieux` et `GET /api/referentiels/agences` (L5-T7) : vue des
référentiels (qui a déposé quoi, quels chantiers n'ont plus rien envoyé) —
voir `ingest/referentiels_vue.py` pour toute la logique métier. Aucune
somme, aucun seuil calculé ici (décision globale du lot 5) : ce routeur
valide les paramètres de requête, appelle le service, sérialise.

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`). Toutes
les routes sont réservées à l'admin (`admin_requis`) : un agent reçoit 403
avant tout accès au service.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import (
    ChantierCreationRequete,
    ChantierModificationRequete,
    ChantierReponse,
    ChantierSilencieuxReponse,
    DepotAgentReponse,
    FournisseurReponse,
    FusionChantierRequete,
    ResultatFusionReponse,
    ValidationAliasReponse,
    ValidationAliasRequete,
    ValidationArticleRequete,
)
from app.modules.ingest.fusion_chantier import FusionImpossible, fusionner_chantiers
from app.modules.ingest.referentiels import (
    AliasDejaValide,
    AliasIntrouvable,
    ArticleIntrouvable,
    ChantierEnDouble,
    ChantierIntrouvable,
    creer_chantier,
    lister_chantiers,
    lister_fournisseurs,
    modifier_chantier,
    obtenir_chantier,
    valider_alias,
    valider_article,
)
from app.modules.ingest.referentiels_vue import (
    DEPOTS_PAR_AGENT_JOURS_DEFAUT,
    agences_connues,
    chantiers_sans_depot,
    depots_par_agent,
)

router = APIRouter()

# Bornes de `jours` sur `GET /api/referentiels/depots-par-agent` (décision du
# contrôleur, brief L5-T7 : « borné ») : un an au plus, jamais `0` (une
# fenêtre vide n'a pas de sens pour ce tableau).
_DEPOTS_JOURS_MIN = 1
_DEPOTS_JOURS_MAX = 365


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
            client=requete.client,
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


@router.put("/chantiers/{chantier_id}", response_model=ChantierReponse)
async def modifier_chantier_endpoint(
    chantier_id: uuid.UUID,
    requete: ChantierModificationRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChantierReponse | JSONResponse:
    try:
        chantier = await modifier_chantier(
            session,
            chantier_id=chantier_id,
            nom_canonique=requete.nom_canonique,
            agence=requete.agence,
            client=requete.client,
            actif=requete.actif,
            auteur_id=utilisateur.id,
        )
    except ChantierIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="chantier introuvable"
        ) from exc
    except ChantierEnDouble as exc:
        # Même corps 409 que `POST /api/chantiers` (`original_id` au même
        # niveau que `detail`).
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "chantier déjà existant.",
                "original_id": str(exc.original_id),
            },
        )
    return ChantierReponse.model_validate(chantier)


@router.get("/chantiers/{chantier_id}", response_model=ChantierReponse)
async def obtenir_chantier_endpoint(
    chantier_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChantierReponse:
    # Renvoie aussi un chantier fusionné (Task 7, spec §2.7) : seule route
    # qui doit encore l'atteindre, pour le bandeau de sa fiche -- à la
    # différence de `GET /api/chantiers`, qui les exclut (Task 6).
    chantier = await obtenir_chantier(session, chantier_id)
    if chantier is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="chantier introuvable"
        )
    return ChantierReponse.model_validate(chantier)


@router.post("/chantiers/{chantier_id}/fusionner", response_model=ResultatFusionReponse)
async def fusionner_chantiers_endpoint(
    chantier_id: uuid.UUID,
    requete: FusionChantierRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ResultatFusionReponse:
    try:
        resultat = await fusionner_chantiers(
            session,
            source_id=chantier_id,
            cible_id=requete.cible_id,
            auteur_id=utilisateur.id,
        )
    except ChantierIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="chantier introuvable"
        ) from exc
    except FusionImpossible as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return ResultatFusionReponse.model_validate(resultat)


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


# ---------------------------------------------------------------------------
# Vue des référentiels (L5-T7)
# ---------------------------------------------------------------------------


@router.get("/referentiels/depots-par-agent", response_model=list[DepotAgentReponse])
async def depots_par_agent_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    jours: Annotated[
        int, Query(ge=_DEPOTS_JOURS_MIN, le=_DEPOTS_JOURS_MAX)
    ] = DEPOTS_PAR_AGENT_JOURS_DEFAUT,
) -> list[DepotAgentReponse]:
    depots = await depots_par_agent(session, jours=jours)
    return [DepotAgentReponse.model_validate(depot) for depot in depots]


@router.get(
    "/referentiels/chantiers-silencieux",
    response_model=list[ChantierSilencieuxReponse],
)
async def chantiers_sans_depot_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ChantierSilencieuxReponse]:
    # Aucun paramètre `jours` ici (décision du contrôleur, `ingest
    # .referentiels_vue.chantiers_sans_depot`) : le seuil est lu depuis la
    # table `parametre` par le service, jamais par ce routeur.
    chantiers = await chantiers_sans_depot(session)
    return [ChantierSilencieuxReponse.model_validate(c) for c in chantiers]


@router.get("/referentiels/agences", response_model=list[str])
async def agences_connues_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[str]:
    return await agences_connues(session)
