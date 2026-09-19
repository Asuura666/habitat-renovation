"""`GET /api/journal` (L5-T9) : lecture paginée du journal de traçabilité —
« qui a validé ça, et quand ? » (CDC §4.6, registre des traitements §8).
Voir `ingest/journal.py` pour toute la logique métier. Route en ajout seul :
aucune écriture, aucune suppression (L5-D10).

Couche d'entrée (L2-D3) : ce routeur n'importe que `app.core` et
`app.modules.ingest` (garde vérifiée par `tests/test_frontieres.py`).
Réservé à l'admin (`admin_requis`, Q4 du plan lot 5 — décision provisoire,
même périmètre que `GET /api/anomalies`) : un agent reçoit 403 avant tout
accès au service.

Filtres de `GET /api/journal` (décision du contrôleur, L5-D10) :
`utilisateur_id`, `action`, `cible_table`, `depuis`/`jusqu_a` (sur
`horodatage`), `limite` (1..500, défaut 100 — même plafond que
`GET /api/anomalies`) — combinables.

`action` et `cible_table` restent de simples chaînes (`str | None`), jamais
un `Literal` fermé comme `RegleAnomalie` dans `api/anomalies.py` :
contrairement au catalogue des 17 règles (`rules.engine`, un registre
canonique que ce routeur ne peut de toute façon pas importer, et que
`test_anomalies.py` vérifie exhaustif), il n'existe aucun registre central
des actions ou des tables cibles du journal — ce sont des chaînes littérales
semées au fil des modules `ingest` qui journalisent (`corrections.py`,
`referentiels.py`, `depot_telegram.py`, ...), et cette tâche n'a pas le
droit d'y toucher (consigne du contrôleur : « tu ne changes rien à ce qui
écrit dans le journal »). Un `Literal` figé ici se désynchroniserait donc
silencieusement à la moindre action ajoutée par un lot futur, sans qu'aucun
test ne puisse le détecter — pire, une action réellement journalisée mais
absente de l'énumération deviendrait injustement infiltrable par le filtre
alors qu'elle reste normalement affichée (défense en profondeur : une
action inconnue du front affiche son code brut, `lib/journal.ts`). `422 sur
un filtre mal formé` (test attendu de la fiche) est couvert par
`utilisateur_id` (UUID invalide) et par `depuis`/`jusqu_a` (date invalide),
comme pour tout autre paramètre typé de cette API — inutile d'ajouter un
registre fermé rien que pour produire ce cas.

`depuis`/`jusqu_a` : même conversion que `api/anomalies.py` (Ruling R21) —
des `date` (`"AAAA-MM-JJ"`, valeur brute d'un `<input type="date">`),
jamais des horodatages ; la conversion en bornes d'instants (début/fin de
journée en Europe/Paris) se fait ici, une seule fois, jamais dans
`ingest.journal.lister_journal` qui ne reçoit que des `datetime` déjà
résolues.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Utilisateur, admin_requis
from app.core.db import get_session
from app.core.fuseau import FUSEAU_PARIS
from app.modules.api.schemas import JournalReponse
from app.modules.ingest.journal import LIMITE_JOURNAL_DEFAUT, lister_journal

router = APIRouter()

_LIMITE_MIN = 1
_LIMITE_MAX = 500


def _debut_jour_paris(jour: date) -> datetime:
    """Voir `api.anomalies._debut_jour_paris` (Ruling R21) — même
    convention, dupliquée ici plutôt que partagée : ni `api.anomalies` ni
    `api.journal` n'exposent de module utilitaire commun pour ces deux
    lignes, et ce lot n'a aucune raison d'en créer un (décision du
    contrôleur : pas de nouvelle indirection pour deux fonctions d'une
    ligne)."""
    return datetime.combine(jour, time.min, tzinfo=FUSEAU_PARIS)


def _fin_jour_paris(jour: date) -> datetime:
    """Symétrique de `_debut_jour_paris` : fin (23:59:59.999999) de `jour`
    en Europe/Paris, borne haute d'une période."""
    return datetime.combine(jour, time.max, tzinfo=FUSEAU_PARIS)


@router.get("/journal", response_model=list[JournalReponse])
async def lister_journal_endpoint(
    utilisateur: Annotated[Utilisateur, Depends(admin_requis)],
    session: Annotated[AsyncSession, Depends(get_session)],
    utilisateur_id: Annotated[uuid.UUID | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    cible_table: Annotated[str | None, Query()] = None,
    depuis: Annotated[date | None, Query()] = None,
    jusqu_a: Annotated[date | None, Query()] = None,
    limite: Annotated[
        int, Query(ge=_LIMITE_MIN, le=_LIMITE_MAX)
    ] = LIMITE_JOURNAL_DEFAUT,
) -> list[JournalReponse]:
    entrees = await lister_journal(
        session,
        utilisateur_id=utilisateur_id,
        action=action,
        cible_table=cible_table,
        depuis=_debut_jour_paris(depuis) if depuis is not None else None,
        jusqu_a=_fin_jour_paris(jusqu_a) if jusqu_a is not None else None,
        limite=limite,
    )
    return [JournalReponse.model_validate(entree) for entree in entrees]
