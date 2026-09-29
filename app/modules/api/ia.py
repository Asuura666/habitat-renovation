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

`GET /api/ia/prix-internet` (T10a) : la même chose que la route précédente,
mais pour plusieurs anomalies d'un coup (`ingest.ia_prix
.prix_internet_des_anomalies`) — décision du contrôleur : une route dédiée
pour la 3ᵉ colonne « Internet » de la page « Prix à vérifier » (lot Prix)
plutôt que d'enrichir `GET /api/prix/alertes`, pour ne jamais faire dépendre
le service du lot Prix (`ingest.prix_bl`) de l'IA.

`GET /api/ia/labo/etat`, `POST /api/ia/labo/essais/{prix,explication,
synthese}`, `GET /api/ia/labo/essais[/{id}]`, `GET /api/ia/labo/appels`
(tâche LABO, brief `task-labo-brief.md`) : écran « Laboratoire IA » — teste
les trois usages de l'IA avant de s'y fier, montre exactement le texte
envoyé, les pages ouvertes, la réponse brute, les contrôles anti-invention et
le résultat, sans jamais rien enregistrer (`ingest.ia_labo`, seule la ligne
`appel_ia` écrite par `ingest.opencode.interroger` existe). Les essais
`POST` s'exécutent en tâche de fond (`fastapi.BackgroundTasks`, même
mécanique qu'`ingest.router.webhook_telegram`) : la fabrique de sessions et
le client HTTP du lifespan (`request.app.state`) leur sont passés, jamais
ceux de la requête (fermée avant leur exécution).

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (jamais `extract` directement — garde vérifiée par
`tests/test_frontieres.py`). Toutes les routes sont réservées à l'admin
(`admin_requis`, même principe qu'`api/comptes.py`) : la synthèse résume des
commentaires (donc, indirectement, des chantiers) et l'avis IA porte sur une
anomalie de prix, deux données qu'un simple agent ne voit normalement qu'au
compte-goutte (`ingest.commentaires`, un bon à la fois ; l'écran « À
régler ») — jamais agrégées ou expliquées par l'IA comme ici. Le Laboratoire
IA va plus loin encore (texte envoyé, réponse brute d'OpenCode) : réservé à
l'admin pour la même raison."""

from __future__ import annotations

import uuid
from typing import Annotated

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import (
    ActionSyntheseReponse,
    AppelIALigneReponse,
    AvisIAReponse,
    EssaiExplicationRequete,
    EssaiLanceReponse,
    EssaiPrixRequete,
    EssaiSyntheseRequete,
    EtatLaboReponse,
    PrixInternetLotReponse,
    PrixInternetReponse,
    SyntheseAccueilReponse,
    TraceEssaiReponse,
    TraceEssaiResumeReponse,
)
from app.modules.ingest.anomalies import AnomalieIntrouvable
from app.modules.ingest.ia_labo import (
    derniers_essais,
    journal_appels,
    lancer_essai_explication,
    lancer_essai_prix,
    lancer_essai_synthese,
    lire_essai,
)
from app.modules.ingest.ia_prix import avis_ia_anomalie, prix_internet_des_anomalies
from app.modules.ingest.ia_synthese import (
    ActionIntrouvable,
    marquer_action,
    vue_accueil,
)
from app.modules.ingest.opencode import (
    appels_du_jour,
    diagnostic_ia,
    ia_appels_max_jour,
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


@router.get("/ia/prix-internet", response_model=PrixInternetLotReponse)
async def prix_internet_lot_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    anomalie_id: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> PrixInternetLotReponse:
    del utilisateur
    try:
        lot = await prix_internet_des_anomalies(session, anomalie_id or [])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return PrixInternetLotReponse(
        ia_active=lot.ia_active,
        prix={
            str(identifiant): (
                PrixInternetReponse.model_validate(vue) if vue is not None else None
            )
            for identifiant, vue in lot.par_anomalie.items()
        },
    )


# --------------------------------------------------------------------------
# Laboratoire IA (tâche LABO) : essais de l'IA avant de s'y fier.
# --------------------------------------------------------------------------


def _get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    """Fabrique de sessions du lifespan (même principe qu'`ingest.router
    .get_sessionmaker`) : un essai ouvre sa propre session en tâche de fond,
    la session de la requête étant fermée avant son exécution."""
    sessions: async_sessionmaker[AsyncSession] = request.app.state.sessions
    return sessions


def _get_http(request: Request) -> httpx.AsyncClient:
    """Client HTTP du lifespan (même principe qu'`ingest.router
    .get_messagerie`)."""
    http: httpx.AsyncClient = request.app.state.http
    return http


@router.get("/ia/labo/etat", response_model=EtatLaboReponse)
async def etat_labo_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    http: Annotated[httpx.AsyncClient, Depends(_get_http)],
) -> EtatLaboReponse:
    del utilisateur
    diagnostic = await diagnostic_ia(http)
    return EtatLaboReponse(
        ia_active=diagnostic.ia_active,
        url_configuree=diagnostic.url_configuree,
        joignable=diagnostic.joignable,
        joignable_detail=diagnostic.joignable_detail,
        agents=sorted(diagnostic.agents),
        abonnement_connecte=diagnostic.abonnement_connecte,
        recherche_web=diagnostic.recherche_web,
        appels_aujourdhui=await appels_du_jour(session),
        appels_max_jour=ia_appels_max_jour(),
    )


@router.post(
    "/ia/labo/essais/prix",
    response_model=EssaiLanceReponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def lancer_essai_prix_endpoint(
    corps: EssaiPrixRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    background_tasks: BackgroundTasks,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(_get_sessionmaker)],
    http: Annotated[httpx.AsyncClient, Depends(_get_http)],
) -> EssaiLanceReponse:
    del utilisateur
    essai_id = await lancer_essai_prix(
        sessions,
        http,
        background_tasks,
        fournisseur=corps.fournisseur,
        designation=corps.designation,
        code=corps.code,
        unite=corps.unite,
    )
    return EssaiLanceReponse(id=essai_id)


@router.post(
    "/ia/labo/essais/explication",
    response_model=EssaiLanceReponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def lancer_essai_explication_endpoint(
    corps: EssaiExplicationRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    background_tasks: BackgroundTasks,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(_get_sessionmaker)],
    http: Annotated[httpx.AsyncClient, Depends(_get_http)],
) -> EssaiLanceReponse:
    del utilisateur
    try:
        essai_id = await lancer_essai_explication(
            sessions, http, background_tasks, corps.anomalie_id
        )
    except AnomalieIntrouvable as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="anomalie introuvable"
        ) from exc
    return EssaiLanceReponse(id=essai_id)


@router.post(
    "/ia/labo/essais/synthese",
    response_model=EssaiLanceReponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def lancer_essai_synthese_endpoint(
    corps: EssaiSyntheseRequete,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    background_tasks: BackgroundTasks,
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(_get_sessionmaker)],
    http: Annotated[httpx.AsyncClient, Depends(_get_http)],
) -> EssaiLanceReponse:
    del utilisateur
    try:
        essai_id = await lancer_essai_synthese(
            sessions, http, background_tasks, corps.semaine_debut
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return EssaiLanceReponse(id=essai_id)


@router.get("/ia/labo/essais/{essai_id}", response_model=TraceEssaiReponse)
async def lire_essai_endpoint(
    essai_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
) -> TraceEssaiReponse:
    del utilisateur
    trace = lire_essai(essai_id)
    if trace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="essai introuvable"
        )
    return TraceEssaiReponse.model_validate(trace)


@router.get("/ia/labo/essais", response_model=list[TraceEssaiResumeReponse])
async def derniers_essais_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
) -> list[TraceEssaiResumeReponse]:
    del utilisateur
    return [
        TraceEssaiResumeReponse.model_validate(essai) for essai in derniers_essais()
    ]


@router.get("/ia/labo/appels", response_model=list[AppelIALigneReponse])
async def journal_appels_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[AppelIALigneReponse]:
    del utilisateur
    lignes = await journal_appels(session, limite=50)
    return [AppelIALigneReponse.model_validate(ligne) for ligne in lignes]
