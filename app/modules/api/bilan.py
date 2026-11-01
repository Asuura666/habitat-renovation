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

Export CSV (L5-T4) : une route `.csv` par route JSON ci-dessus, même
service, mêmes filtres, jamais une deuxième requête -- `ingest/export.py`
sérialise les mêmes dataclasses en CSV (`csv_bilan_chantiers`,
`csv_bilan_fournisseurs`, `csv_bilan_bl`), ce routeur n'y ajoute que ce qui
est propre à HTTP : le BOM UTF-8 (décision du contrôleur -- la fonction de
sérialisation ne le porte pas, elle produit du CSV, pas une réponse HTTP) et
le nom de fichier du téléchargement (`_nom_fichier_csv`, qui dit le niveau
et la période, jamais d'accent ni d'espace). `GET /api/bilan/fournisseurs.csv`
et `GET /api/bilan/chantiers/{id}/fournisseurs.csv` réutilisent la même
fonction de sérialisation (`csv_bilan_fournisseurs`) : les deux routes JSON
correspondantes renvoient déjà la même forme (`LigneBilanFournisseurReponse`).

Export détaillé (décision d'Ilane du 23/09/2026, réponse à Q3 du lot 5) :
`GET /api/bilan/detail.csv`, sans route JSON équivalente (ce niveau n'a pas
sa place à l'écran, seulement dans le fichier que le client ouvre dans
Excel) -- même service (`ingest.bilan.bilan_detail`), même sérialisation
(`ingest.export.csv_bilan_detail`), mêmes paramètres `mois`/`agence`, même
contrôle admin, même `_reponse_csv`/`_nom_fichier_csv` que les six routes
ci-dessus.
"""

from __future__ import annotations

import codecs
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.modules.api.schemas import (
    LigneBilanBlReponse,
    LigneBilanChantierReponse,
    LigneBilanFournisseurReponse,
    LigneLivraisonReponse,
)
from app.modules.ingest.bilan import (
    bilan_chantiers_du_fournisseur,
    bilan_detail,
    bilan_par_bl,
    bilan_par_chantier,
    bilan_par_fournisseur,
    bilan_par_fournisseur_global,
    lister_livraisons,
)
from app.modules.ingest.export import (
    csv_bilan_bl,
    csv_bilan_chantiers,
    csv_bilan_detail,
    csv_bilan_fournisseurs,
    csv_livraisons,
)

router = APIRouter()

_REPONSES_CSV: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Export CSV UTF-8 du bilan.",
        "content": {"text/csv": {"schema": {"type": "string"}}},
    }
}


def _nom_fichier_csv(niveau: str, mois: date | None) -> str:
    """Nom de fichier du téléchargement (`Content-Disposition`) -- dit le
    niveau et la période (décision du contrôleur), jamais d'accent ni
    d'espace. `mois` peut être n'importe quel jour du mois filtré (le
    service le ramène lui-même à son mois calendaire, voir le docstring
    d'en-tête) : seuls l'année et le mois du paramètre reçu entrent dans le
    nom, jamais le jour."""
    if mois is None:
        return f"bilan-{niveau}.csv"
    return f"bilan-{niveau}-{mois.strftime('%Y-%m')}.csv"


def _reponse_csv(contenu_csv: str, *, nom_fichier: str) -> Response:
    """Réponse HTTP d'un export CSV. Le BOM UTF-8 (`codecs.BOM_UTF8`) est
    ajouté ici, pas dans `ingest.export` (décision du contrôleur) : ce
    module construit une réponse HTTP, `ingest.export` produit du CSV --
    deux responsabilités distinctes, jamais mélangées."""
    corps = codecs.BOM_UTF8 + contenu_csv.encode("utf-8")
    return Response(
        content=corps,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


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


@router.get(
    "/bilan/fournisseurs/{fournisseur_id}/chantiers",
    response_model=list[LigneBilanChantierReponse],
)
async def bilan_chantiers_du_fournisseur_endpoint(
    fournisseur_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
) -> list[LigneBilanChantierReponse]:
    lignes = await bilan_chantiers_du_fournisseur(
        session, fournisseur_id=fournisseur_id, mois=mois, agence=agence
    )
    return [LigneBilanChantierReponse.model_validate(ligne) for ligne in lignes]


@router.get("/bilan/livraisons", response_model=list[LigneLivraisonReponse])
async def bilan_livraisons_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
    chantier: Annotated[uuid.UUID | None, Query()] = None,
    fournisseur: Annotated[uuid.UUID | None, Query()] = None,
) -> list[LigneLivraisonReponse]:
    """Liste des livraisons (Task 13, mise en production du 1er octobre,
    spec §4.3) : bons conformes cliquables (accueil, fiche chantier, fiche
    fournisseur) et écran `/livraisons`. `chantier`/`fournisseur` absents ->
    aucun filtre sur ce côté (voir `ingest.bilan.lister_livraisons`, dont le
    docstring explique pourquoi `None` n'y sélectionne pas le côté non
    résolu comme les autres routes de ce module)."""
    lignes = await lister_livraisons(
        session,
        mois=mois,
        agence=agence,
        chantier_id=chantier,
        fournisseur_id=fournisseur,
    )
    return [LigneLivraisonReponse.model_validate(ligne) for ligne in lignes]


# --------------------------------------------------------------------------
# Export CSV (L5-T4) : une route `.csv` par route JSON ci-dessus, même
# service, mêmes filtres, même tri -- voir le docstring d'en-tête.
# --------------------------------------------------------------------------


@router.get("/bilan/chantiers.csv", response_class=Response, responses=_REPONSES_CSV)
async def bilan_chantiers_csv_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
) -> Response:
    lignes = await bilan_par_chantier(session, mois=mois, agence=agence)
    return _reponse_csv(
        csv_bilan_chantiers(lignes), nom_fichier=_nom_fichier_csv("chantiers", mois)
    )


@router.get(
    "/bilan/chantiers/{chantier_id}/fournisseurs.csv",
    response_class=Response,
    responses=_REPONSES_CSV,
)
async def bilan_fournisseurs_du_chantier_csv_endpoint(
    chantier_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
) -> Response:
    lignes = await bilan_par_fournisseur(
        session, chantier_id=chantier_id, mois=mois, agence=agence
    )
    return _reponse_csv(
        csv_bilan_fournisseurs(lignes),
        nom_fichier=_nom_fichier_csv("fournisseurs", mois),
    )


@router.get(
    "/bilan/chantiers/{chantier_id}/fournisseurs/{fournisseur_id}/bl.csv",
    response_class=Response,
    responses=_REPONSES_CSV,
)
async def bilan_bl_csv_endpoint(
    chantier_id: uuid.UUID,
    fournisseur_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
) -> Response:
    # Pas de filtre `agence` ici, même raison que la route JSON équivalente
    # (le chantier est déjà fixé par `chantier_id`).
    lignes = await bilan_par_bl(
        session, chantier_id=chantier_id, fournisseur_id=fournisseur_id, mois=mois
    )
    return _reponse_csv(csv_bilan_bl(lignes), nom_fichier=_nom_fichier_csv("bl", mois))


@router.get("/bilan/fournisseurs.csv", response_class=Response, responses=_REPONSES_CSV)
async def bilan_fournisseurs_csv_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
) -> Response:
    """Vue inverse (même niveau que `bilan_fournisseurs_endpoint`) : même
    fonction de sérialisation que la route `.csv` imbriquée dans un
    chantier ci-dessus, les deux renvoyant des `LigneBilanFournisseur`."""
    lignes = await bilan_par_fournisseur_global(session, mois=mois, agence=agence)
    return _reponse_csv(
        csv_bilan_fournisseurs(lignes),
        nom_fichier=_nom_fichier_csv("fournisseurs", mois),
    )


@router.get(
    "/bilan/fournisseurs/{fournisseur_id}/chantiers.csv",
    response_class=Response,
    responses=_REPONSES_CSV,
)
async def bilan_chantiers_du_fournisseur_csv_endpoint(
    fournisseur_id: uuid.UUID,
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
) -> Response:
    lignes = await bilan_chantiers_du_fournisseur(
        session, fournisseur_id=fournisseur_id, mois=mois, agence=agence
    )
    return _reponse_csv(
        csv_bilan_chantiers(lignes),
        nom_fichier=_nom_fichier_csv("chantiers", mois),
    )


@router.get("/bilan/detail.csv", response_class=Response, responses=_REPONSES_CSV)
async def bilan_detail_csv_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
) -> Response:
    """Export détaillé (décision d'Ilane du 23/09/2026, réponse à Q3 du lot
    5) : une ligne par ligne de facture, sur tout le périmètre filtré --
    voir `ingest.bilan.bilan_detail`/`ingest.export.csv_bilan_detail`."""
    lignes = await bilan_detail(session, mois=mois, agence=agence)
    return _reponse_csv(
        csv_bilan_detail(lignes), nom_fichier=_nom_fichier_csv("detail", mois)
    )


@router.get("/bilan/livraisons.csv", response_class=Response, responses=_REPONSES_CSV)
async def bilan_livraisons_csv_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    mois: Annotated[date | None, Query()] = None,
    agence: Annotated[str | None, Query()] = None,
    chantier: Annotated[uuid.UUID | None, Query()] = None,
    fournisseur: Annotated[uuid.UUID | None, Query()] = None,
) -> Response:
    """Lot 2, B3 : la liste des livraisons (lignes de facture et bons pas
    encore facturés) en CSV, mêmes filtres que la route JSON."""
    lignes = await lister_livraisons(
        session,
        mois=mois,
        agence=agence,
        chantier_id=chantier,
        fournisseur_id=fournisseur,
    )
    return _reponse_csv(
        csv_livraisons(lignes), nom_fichier=_nom_fichier_csv("livraisons", mois)
    )
