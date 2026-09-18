"""`GET /api/bilan/...` (L5-T3) : lecture agrégée du bilan, exposée en HTTP
-- voir `ingest/bilan.py` (L5-T1/L5-T2, commité, non modifié ici) pour toute
la logique de calcul (les quatre montants, L5-D3 ; le mois d'un bloc, L5-D4).

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`).
Réservé à l'admin (`admin_requis`), même principe qu'`api/anomalies.py` (le
modèle suivi ici, décision du contrôleur) : un agent reçoit 403 avant tout
accès au service. Aucune règle métier ici : ce routeur valide, appelle le
service, sérialise -- aucune somme, aucun seuil, aucun tri.

Filtre `mois` (décision du contrôleur) : une `date`, jamais une chaîne
libre -- FastAPI/Pydantic la valide (422 sur une valeur mal formée) avant
que le routeur ne la voie. Le service (`ingest.bilan._condition_mois`)
ramène lui-même toute date à son 1er du mois calendaire parisien : le
routeur ne refuse ni ne corrige rien, il la transmet telle quelle (piège
signalé par le contrôleur -- refuser une date qui n'est pas un 1er du mois
serait une contrainte que rien n'impose à l'appelant).

Chantier/fournisseur inconnu -> liste vide, jamais 404 (décision du
contrôleur) : ce sont des vues sur un ensemble de blocs, pas des ressources
identifiées -- interroger le bilan d'un chantier qui n'a rien facturé ce
mois-ci est une question légitime dont la réponse est « rien ». Aucune
vérification d'existence n'est donc faite ici : le service renvoie
naturellement une liste vide quand le périmètre est vide.

`GET /api/bilan/agences` n'est **pas** exposée par ce module. Le service
correspondant (`ingest.referentiels_vue.agences_connues`) vit dans le
périmètre de l'autre agent du lot 5 (branche `lot-5-referentiels`,
`/home/debian/habitat_reno-wt-l5`) et n'est pas encore fusionné dans cette
branche (`lot-5-restitution`) : le fichier n'existe pas ici. Décision du
contrôleur (fiche L5-T3) : ne jamais dupliquer cette lecture, signaler
plutôt que d'inventer une deuxième requête -- voir `L5-T3-report.md` pour le
détail transmis au contrôleur. Câblage prévu une fois le module disponible
sur cette branche :

    from app.modules.ingest.referentiels_vue import agences_connues

    @router.get("/bilan/agences", response_model=list[str])
    async def bilan_agences_endpoint(
        utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> list[str]:
        return await agences_connues(session)
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import (
    LigneBilanBlReponse,
    LigneBilanChantierReponse,
    LigneBilanFournisseurReponse,
)
from app.modules.ingest.bilan import (
    bilan_par_bl,
    bilan_par_chantier,
    bilan_par_fournisseur,
    bilan_par_fournisseur_global,
)

router = APIRouter()


@router.get("/bilan/chantiers", response_model=list[LigneBilanChantierReponse])
async def bilan_chantiers_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
) -> list[LigneBilanChantierReponse]:
    lignes = await bilan_par_chantier(session, mois=mois, agence=agence)
    return [LigneBilanChantierReponse.model_validate(ligne) for ligne in lignes]


@router.get(
    "/bilan/chantiers/{chantier_id}/fournisseurs",
    response_model=list[LigneBilanFournisseurReponse],
)
async def bilan_fournisseurs_du_chantier_endpoint(
    chantier_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
) -> list[LigneBilanFournisseurReponse]:
    lignes = await bilan_par_fournisseur(
        session, chantier_id=chantier_id, mois=mois, agence=agence
    )
    return [LigneBilanFournisseurReponse.model_validate(ligne) for ligne in lignes]


@router.get(
    "/bilan/chantiers/{chantier_id}/fournisseurs/{fournisseur_id}/bl",
    response_model=list[LigneBilanBlReponse],
)
async def bilan_bl_endpoint(
    chantier_id: uuid.UUID,
    fournisseur_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
) -> list[LigneBilanBlReponse]:
    # Pas de filtre `agence` ici (absent de la fiche pour ce niveau) : le
    # chantier est déjà fixé par `chantier_id`, l'agence n'y ajoute aucune
    # restriction supplémentaire (décision du contrôleur).
    lignes = await bilan_par_bl(
        session, chantier_id=chantier_id, fournisseur_id=fournisseur_id, mois=mois
    )
    return [LigneBilanBlReponse.model_validate(ligne) for ligne in lignes]


@router.get("/bilan/fournisseurs", response_model=list[LigneBilanFournisseurReponse])
async def bilan_fournisseurs_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
) -> list[LigneBilanFournisseurReponse]:
    """Vue inverse (L5-T2) : bilan agrégé par fournisseur sur l'ensemble des
    chantiers -- point d'entrée de la navigation « du fournisseur vers le
    chantier »."""
    lignes = await bilan_par_fournisseur_global(session, mois=mois, agence=agence)
    return [LigneBilanFournisseurReponse.model_validate(ligne) for ligne in lignes]
