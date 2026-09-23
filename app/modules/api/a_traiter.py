"""`GET /api/a-traiter` (L3-T8b) : écran « À traiter » de l'admin — documents
« à vérifier » (BL, enlèvements et factures), alias chantier en attente de
validation, articles à valider, anomalies ouvertes de gravité haute
(`anomalies_hautes`, L4-D18, L4-T9).

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`). Toute
la requête SQL vit dans `ingest.a_traiter.lister_a_traiter` et
`ingest.anomalies.lister_anomalies` — ce routeur ne fait qu'appeler les deux
et sérialiser, sans dupliquer de requête dédiée (décision du contrôleur,
L4-D18 : réutiliser `lister_anomalies` plutôt qu'écrire une nouvelle
fonction). Réservé à l'admin (`admin_requis`, L3-D18) : un agent reçoit 403.

`GET /api/a-regler/compte` (revue finale de la refonte du front) : le compte
unique des problèmes « à régler », tous mois confondus
(`ingest.a_traiter.compter_problemes_a_regler`), lu par la pastille de
navigation, la vue d'ensemble et l'écran « À régler » -- réservé à l'admin
comme le reste de ce routeur.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import (
    AliasEnAttenteReponse,
    AnomalieReponse,
    ArticleAValiderReponse,
    ATraiterReponse,
    CompteProblemesReponse,
    DocumentATraiterReponse,
)
from app.modules.ingest.a_traiter import compter_problemes_a_regler, lister_a_traiter
from app.modules.ingest.anomalies import lister_anomalies

router = APIRouter()

# Section « anomalies ouvertes de gravité haute » de l'écran (CDC §4.6,
# L4-D18) : les 20 plus anciennes, valeur donnée par la fiche.
_LIMITE_ANOMALIES_HAUTES = 20


@router.get("/a-traiter", response_model=ATraiterReponse)
async def obtenir_a_traiter(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ATraiterReponse:
    a_traiter = await lister_a_traiter(session)
    anomalies_hautes = await lister_anomalies(
        session,
        gravite="haute",
        statut="ouverte",
        limite=_LIMITE_ANOMALIES_HAUTES,
    )
    return ATraiterReponse(
        documents=[
            DocumentATraiterReponse.model_validate(document)
            for document in a_traiter.documents
        ],
        alias=[
            AliasEnAttenteReponse.model_validate(alias) for alias in a_traiter.alias
        ],
        articles=[
            ArticleAValiderReponse.model_validate(article)
            for article in a_traiter.articles
        ],
        anomalies_hautes=[
            AnomalieReponse.model_validate(anomalie) for anomalie in anomalies_hautes
        ],
    )


@router.get("/a-regler/compte", response_model=CompteProblemesReponse)
async def obtenir_compte_a_regler(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CompteProblemesReponse:
    compte = await compter_problemes_a_regler(session)
    return CompteProblemesReponse.model_validate(compte)
