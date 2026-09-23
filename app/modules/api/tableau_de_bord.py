"""`GET /api/tableau-de-bord` (refonte front T2) : lecture du tableau de
bord du mois -- voir `ingest/tableau_de_bord.py` (commité, non modifié ici)
pour toute la logique de calcul (totaux, état par chantier, priorités).

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`).
Réservé à l'admin (`admin_requis`), même principe qu'`api/bilan.py`/
`api/anomalies.py` : un agent reçoit 403 avant tout accès au service. Aucune
règle métier ici : ce routeur valide, appelle le service, sérialise --
aucune somme, aucun seuil, aucun tri.

`mois` est obligatoire (décision du brief T2, à la différence de `GET
/api/bilan/chantiers` où il est optionnel) : le tableau de bord n'a pas de
sens "tous mois confondus". Même type `date` que le filtre du bilan --
FastAPI/Pydantic la valide (422 si absente ou mal formée) avant que le
routeur ne la voie ; le service (`ingest.bilan._condition_mois`, réutilisé
par `ingest.tableau_de_bord`) ramène lui-même toute date à son 1er du mois
calendaire parisien, jamais corrigée ici (même piège évité qu'`api/bilan.py`).

Mois sans donnée -> 200 avec `chantiers`/`priorites` vides, jamais 404
(même décision qu'`api/bilan.py` pour un chantier/fournisseur inconnu) :
c'est une réponse légitime, pas une ressource absente.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import TableauDeBordReponse
from app.modules.ingest.tableau_de_bord import tableau_de_bord

router = APIRouter()


@router.get("/tableau-de-bord", response_model=TableauDeBordReponse)
async def tableau_de_bord_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date, Query()],
) -> TableauDeBordReponse:
    tdb = await tableau_de_bord(session, mois=mois)
    return TableauDeBordReponse.model_validate(tdb)
