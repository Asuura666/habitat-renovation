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

Fix round 1 (ruling R15 du contrôleur, CDC §4.6 : l'admin doit pouvoir
revoir ce qui a déjà été décidé) : `statut` accepte aussi `"toutes"`, qui
retire le filtre de statut — traduit ici en `statut=None` passé au service
(`ingest.anomalies.lister_anomalies` n'a jamais eu de sentinelle
« toutes », un `str | None` suffisait déjà : aucune vraie anomalie n'est
jamais nommée « toutes », donc `Literal` + traduction dans le routeur,
jamais dans le service).

Ruling R21 (revue finale du lot 4, Important) : `depuis`/`jusqu_a` sont des
`date` (`"AAAA-MM-JJ"`, valeur brute d'un `<input type="date">` du front),
pas des horodatages — une borne de période est un jour, pas un instant.
Avant ce correctif, le front fabriquait un horodatage naïf
(`"AAAA-MM-JJT00:00:00"`/`"...T23:59:59"`), lu tel quel par Pydantic alors
que la session Postgres est en UTC et que tout l'affichage est en
Europe/Paris : décalage silencieux de 1 à 2 h selon l'heure d'été. La
conversion en instants (début/fin de journée en Europe/Paris) se fait ici,
dans le routeur, une seule fois, par `_debut_jour_paris`/`_fin_jour_paris`
— même endroit et même convention que la traduction `statut="toutes"` ci-
dessus : ce routeur valide et convertit déjà ce que FastAPI ne peut pas
faire seul, `ingest.anomalies.lister_anomalies` continue de ne recevoir que
des `datetime` déjà résolues, sans rien savoir d'un fuseau.

Ruling R22 (revue finale du lot 4, Minor) : `regle` est validé par
l'énumération `RegleAnomalie` (une faute de frappe renvoie 422, comme pour
`gravite`/`statut`), plutôt que le `str | None` d'origine qui laissait
passer n'importe quelle valeur (200, liste vide). Ce routeur n'a pas le
droit d'importer `rules` (garde `tests/test_frontieres.py`), donc
`RegleAnomalie` est une liste écrite ici ; `test_anomalies.py` (le seul
fichier autorisé à importer les deux) vérifie qu'elle couvre exactement
`REGLES_FACTURE | REGLES_SUIVI` (`rules.engine`), pour ne jamais se
désynchroniser en silence à la première règle ajoutée.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.core.fuseau import FUSEAU_PARIS
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

# Catalogue des 17 règles (CDC §5, Ruling R22) : couverture verrouillée par
# `test_regle_anomalie_couvre_exactement_les_regles_du_moteur`
# (`app/modules/api/tests/test_anomalies.py`), seul endroit autorisé à
# importer à la fois `api` et `rules` pour comparer les deux ensembles.
RegleAnomalie = Literal[
    "R01",
    "R02",
    "R03",
    "R04",
    "R05",
    "R06",
    "R07",
    "R08",
    "R09",
    "R10",
    "R11",
    "R12",
    "R13",
    "R14",
    "R15",
    "R16",
    "R17",
]


def _debut_jour_paris(jour: date) -> datetime:
    """Instant (tz-aware) du début (00:00:00.000000) de `jour` en
    Europe/Paris (Ruling R21) : borne basse d'une période, comparée à
    `Anomalie.created_at` (colonne `DateTime(timezone=True)`, comparaison
    par instant, indépendante du fuseau de la session Postgres)."""
    return datetime.combine(jour, time.min, tzinfo=FUSEAU_PARIS)


def _fin_jour_paris(jour: date) -> datetime:
    """Symétrique de `_debut_jour_paris` : fin (23:59:59.999999) de `jour`
    en Europe/Paris, borne haute d'une période."""
    return datetime.combine(jour, time.max, tzinfo=FUSEAU_PARIS)


@router.get("/anomalies", response_model=list[AnomalieReponse])
async def lister_anomalies_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    regle: Annotated[RegleAnomalie | None, Query()] = None,
    gravite: Annotated[Literal["haute", "moyenne", "basse"] | None, Query()] = None,
    statut: Annotated[
        Literal["ouverte", "traitee", "ignoree", "toutes"], Query()
    ] = "ouverte",
    bloc_id: Annotated[uuid.UUID | None, Query()] = None,
    chantier_id: Annotated[uuid.UUID | None, Query()] = None,
    fournisseur_id: Annotated[uuid.UUID | None, Query()] = None,
    depuis: Annotated[date | None, Query()] = None,
    jusqu_a: Annotated[date | None, Query()] = None,
    limite: Annotated[
        int, Query(ge=_LIMITE_MIN, le=_LIMITE_MAX)
    ] = LIMITE_ANOMALIES_DEFAUT,
) -> list[AnomalieReponse]:
    anomalies = await lister_anomalies(
        session,
        regle=regle,
        gravite=gravite,
        statut=statut if statut != "toutes" else None,
        bloc_id=bloc_id,
        chantier_id=chantier_id,
        fournisseur_id=fournisseur_id,
        depuis=_debut_jour_paris(depuis) if depuis is not None else None,
        jusqu_a=_fin_jour_paris(jusqu_a) if jusqu_a is not None else None,
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
