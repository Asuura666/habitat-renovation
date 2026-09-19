"""Lecture paginée du journal (`ingest/journal.py`, L5-T9) : traçabilité de
toute modification de donnée métier depuis le lot 1 (table `journal`,
ajout seul). Ce module ne fait strictement que lire — aucune écriture,
aucune suppression (L5-D10, rappel du contrôleur : « si tu te retrouves à
écrire un POST, c'est que tu as dérivé »).

Décisions du contrôleur (L5-T9) :
- Modèle suivi : `ingest.anomalies.lister_anomalies`/`AnomalieLue` (lecture
  filtrée, paginée, avec résolution du nom d'un utilisateur plutôt que son
  UUID brut). `JournalLue.auteur` reprend exactement la même mécanique que
  `AnomalieLue.traitee_par` (`coalesce(nom, email)`) : c'est la valeur
  affichée par le front. `auteur is None` (comme `utilisateur_id is None`)
  signifie une décision automatique — convention du projet depuis le lot 1
  (ex. `anomalie_levee`, `extraction_bl`). Le libellé « Automatique » qui en
  découle est un choix d'affichage posé par le front (`Journal.tsx`),
  jamais ici : ce service renvoie `None`, sans le traduire.
- Tri du plus récent au plus ancien sur `horodatage` — le champ métier
  « quand cette action a eu lieu » (`Journal.horodatage`), distinct de
  `created_at` (bookkeeping générique posé sur chaque table, jamais utilisé
  pour l'affichage ou le tri ici). `id` en clé de départage (décision du
  contrôleur : « une dernière clé d'identifiant pour que l'ordre soit
  stable ») pour deux entrées à `horodatage` strictement identique (même
  transaction, ex. les trois `extraction_bl` d'un même document).
- Aucune recherche dans `avant`/`apres` (L5-D10 : JSONB, coûteux, non
  demandé). Seuls quatre filtres, combinables : auteur (`utilisateur_id`),
  action, table cible (`cible_table`), période (`depuis`/`jusqu_a`, des
  instants déjà résolus — la conversion depuis une date civile parisienne
  est la responsabilité de l'appelant, comme pour `lister_anomalies`).
  `avant`/`apres` sont renvoyés tels quels (`dict[str, Any] | None`) :
  aucune interprétation métier ici, la mise en forme lisible revient à
  l'écran (`Journal.tsx`).
- `limite` est bornée par l'appelant (le routeur), comme `limite` dans
  `lister_anomalies`/`lister_documents` : ce service ne connaît ni la
  valeur par défaut d'affichage ni les bornes de validation HTTP, seulement
  `LIMITE_JOURNAL_DEFAUT` (repli si l'appelant n'en fournit pas).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import Journal, Utilisateur

LIMITE_JOURNAL_DEFAUT = 100


@dataclass(frozen=True)
class JournalLue:
    """Une entrée de journal, telle qu'exposée à l'API (`GET /api/journal`,
    L5-T9) — mêmes colonnes que `Journal` (ORM), plus `auteur` (nom résolu,
    voir docstring de module)."""

    id: uuid.UUID
    utilisateur_id: uuid.UUID | None
    auteur: str | None
    action: str
    cible_table: str | None
    cible_id: str | None
    avant: dict[str, Any] | None
    apres: dict[str, Any] | None
    horodatage: datetime


def _journal_lue(ligne: Any) -> JournalLue:
    entree, auteur = ligne
    return JournalLue(
        id=entree.id,
        utilisateur_id=entree.utilisateur_id,
        auteur=auteur,
        action=entree.action,
        cible_table=entree.cible_table,
        cible_id=entree.cible_id,
        avant=entree.avant,
        apres=entree.apres,
        horodatage=entree.horodatage,
    )


async def lister_journal(
    session: AsyncSession,
    *,
    utilisateur_id: uuid.UUID | None = None,
    action: str | None = None,
    cible_table: str | None = None,
    depuis: datetime | None = None,
    jusqu_a: datetime | None = None,
    limite: int = LIMITE_JOURNAL_DEFAUT,
) -> list[JournalLue]:
    """Liste des entrées de journal (`GET /api/journal`, admin uniquement,
    L5-D10), filtres combinables, triée par `horodatage` décroissant puis
    `id` décroissant (ordre stable, décision du contrôleur — voir docstring
    de module). `limite` est bornée par l'appelant (le routeur), comme
    `ingest.anomalies.lister_anomalies`.

    `depuis`/`jusqu_a` portent sur `Journal.horodatage` (le champ métier,
    jamais `created_at`) et sont déjà des instants résolus : la conversion
    depuis une date civile parisienne (`<input type="date">` du front) est
    faite par le routeur (`api/journal.py`), comme pour
    `api/anomalies.py::_debut_jour_paris`/`_fin_jour_paris`."""
    conditions: list[Any] = []
    if utilisateur_id is not None:
        conditions.append(Journal.utilisateur_id == utilisateur_id)
    if action is not None:
        conditions.append(Journal.action == action)
    if cible_table is not None:
        conditions.append(Journal.cible_table == cible_table)
    if depuis is not None:
        conditions.append(Journal.horodatage >= depuis)
    if jusqu_a is not None:
        conditions.append(Journal.horodatage <= jusqu_a)

    resultat = await session.execute(
        select(Journal, func.coalesce(Utilisateur.nom, Utilisateur.email))
        .outerjoin(Utilisateur, Utilisateur.id == Journal.utilisateur_id)
        .where(*conditions)
        .order_by(Journal.horodatage.desc(), Journal.id.desc())
        .limit(limite)
    )
    return [_journal_lue(ligne) for ligne in resultat.all()]
