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

Task 12 (spec §4.1, corrections de mise en production) : `JournalLue.noms`
résout en langage courant les identifiants portés par `avant`/`apres` — le
client voyait un UUID brut sous « Confirmé par » ou un fournisseur. Clés
résolues (mêmes noms que les colonnes qu'elles désignent, décision du
contrôleur) : `confirme_par`/`utilisateur_id`/`deposant_id`/`traitee_par`
(→ `coalesce(nom, email)` d'`Utilisateur`, même mécanique que `auteur`
ci-dessus), `chantier_id` et `cible_id` quand `cible_table == "chantier"`
(→ `Chantier.nom_canonique`), `fournisseur_id` (→ `Fournisseur.nom`). Une
valeur non-UUID ou un identifiant introuvable (compte supprimé, par
exemple) reste simplement absent de `noms` — jamais une clé à valeur
`None`, qui laisserait croire à une recherche faite mais infructueuse
distincte d'une recherche jamais faite (le front les traite pareil : « clé
d'identifiant connue, nom absent » → « (inconnu) », `lib/journal.ts`).

Résolution **groupée**, jamais une requête par entrée (consigne du
contrôleur) : les identifiants sont d'abord collectés sur toute la page
(un ensemble par table concernée), puis trois requêtes au plus
(`Utilisateur`/`Chantier`/`Fournisseur`, chacune un seul `WHERE id IN
(...)`) résolvent l'ensemble de la page — `noms` de chaque `JournalLue` est
ensuite le sous-ensemble de ces résultats que cette entrée référence
réellement (jamais l'ensemble entier de la page, qui exposerait des noms
sans rapport avec l'entrée à qui les lit)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.models import Chantier, Fournisseur, Journal, Utilisateur

LIMITE_JOURNAL_DEFAUT = 100

# Clés de détail (`avant`/`apres`) qui désignent un compte utilisateur
# (Task 12) — `deposant_id`/`traitee_par` ne sont aujourd'hui jamais écrites
# telles quelles dans `avant`/`apres` par le code (seules des colonnes ORM
# portent ces noms), mais figurent dans le contrat de cette fonction pour
# une future écriture qui les journaliserait directement, sans qu'il faille
# retoucher ce module (décision du contrôleur, brief Task 12).
_CLES_UTILISATEUR = ("confirme_par", "utilisateur_id", "deposant_id", "traitee_par")
_CLE_CHANTIER = "chantier_id"
_CLE_CIBLE = "cible_id"
_CLE_FOURNISSEUR = "fournisseur_id"


@dataclass(frozen=True)
class JournalLue:
    """Une entrée de journal, telle qu'exposée à l'API (`GET /api/journal`,
    L5-T9) — mêmes colonnes que `Journal` (ORM), plus `auteur` (nom résolu,
    voir docstring de module) et `noms` (Task 12, résolution des
    identifiants portés par `avant`/`apres`, voir docstring de module)."""

    id: uuid.UUID
    utilisateur_id: uuid.UUID | None
    auteur: str | None
    action: str
    cible_table: str | None
    cible_id: str | None
    avant: dict[str, Any] | None
    apres: dict[str, Any] | None
    horodatage: datetime
    noms: dict[str, str]


def _uuid_ou_none(valeur: Any) -> uuid.UUID | None:
    """Une valeur de détail qui désigne potentiellement un identifiant :
    uniquement une chaîne UUID valide, sinon `None` (valeur absente ou
    non-UUID — décision du contrôleur, Task 12 : un identifiant non-UUID
    reste simplement absent de `noms`, jamais une erreur)."""
    if not isinstance(valeur, str):
        return None
    try:
        return uuid.UUID(valeur)
    except ValueError:
        return None


def _ids_references(
    entree: Journal,
) -> tuple[set[uuid.UUID], set[uuid.UUID], set[uuid.UUID]]:
    """Identifiants référencés par `avant`/`apres` d'une entrée (Task 12,
    voir docstring de module) : utilisateurs, chantiers, fournisseurs.
    `cible_id` n'est traitée comme un chantier que si `cible_table` de
    cette entrée vaut `"chantier"` (seul cas réel aujourd'hui,
    `fusion_chantier.py::fusionner_chantiers`) — un `cible_id` de
    `"parametre"` ou d'un autre type n'est jamais un identifiant de
    chantier.

    `cible_id` lui-même (la colonne, pas une clé d'`avant`/`apres`) est le
    compte visé quand `cible_table` vaut `"utilisateur"` (actions de
    l'écran Comptes, `app/core/auth.py`) : résolu en nom comme les autres
    utilisateurs, pour que la colonne « Cible » n'affiche jamais un
    identifiant (recette du 28/09/2026)."""
    utilisateurs: set[uuid.UUID] = set()
    chantiers: set[uuid.UUID] = set()
    fournisseurs: set[uuid.UUID] = set()
    if entree.cible_table == "utilisateur":
        compte_cible = _uuid_ou_none(entree.cible_id)
        if compte_cible is not None:
            utilisateurs.add(compte_cible)
    for contexte in (entree.avant, entree.apres):
        if contexte is None:
            continue
        for cle in _CLES_UTILISATEUR:
            identifiant = _uuid_ou_none(contexte.get(cle))
            if identifiant is not None:
                utilisateurs.add(identifiant)
        identifiant_chantier = _uuid_ou_none(contexte.get(_CLE_CHANTIER))
        if identifiant_chantier is not None:
            chantiers.add(identifiant_chantier)
        if entree.cible_table == "chantier":
            identifiant_cible = _uuid_ou_none(contexte.get(_CLE_CIBLE))
            if identifiant_cible is not None:
                chantiers.add(identifiant_cible)
        identifiant_fournisseur = _uuid_ou_none(contexte.get(_CLE_FOURNISSEUR))
        if identifiant_fournisseur is not None:
            fournisseurs.add(identifiant_fournisseur)
    return utilisateurs, chantiers, fournisseurs


async def _noms_par_id(
    session: AsyncSession,
    colonne_id: Any,
    colonne_nom: Any,
    ids: set[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Une requête groupée pour toute la page (jamais une par entrée,
    consigne du contrôleur) : `{}` sans requête si aucune entrée de la page
    ne référence cette table. `colonne_id`/`colonne_nom` typées `Any`
    (décision du contrôleur) : `Utilisateur.id`/`Chantier.id`/`Fournisseur
    .id` sont des `InstrumentedAttribute`, `func.coalesce(...)` une
    fonction SQL -- aucun type commun ne couvre les trois sans perdre
    `.in_()` sur `colonne_id`."""
    if not ids:
        return {}
    lignes = await session.execute(
        select(colonne_id, colonne_nom).where(colonne_id.in_(ids))
    )
    return {identifiant: nom for identifiant, nom in lignes.all()}


def _journal_lue(
    ligne: Any,
    ids_entree: tuple[set[uuid.UUID], set[uuid.UUID], set[uuid.UUID]],
    noms_utilisateurs: dict[uuid.UUID, str],
    noms_chantiers: dict[uuid.UUID, str],
    noms_fournisseurs: dict[uuid.UUID, str],
) -> JournalLue:
    entree, auteur = ligne
    utilisateurs_ids, chantiers_ids, fournisseurs_ids = ids_entree
    noms: dict[str, str] = {}
    for identifiant, table_noms in (
        *((i, noms_utilisateurs) for i in utilisateurs_ids),
        *((i, noms_chantiers) for i in chantiers_ids),
        *((i, noms_fournisseurs) for i in fournisseurs_ids),
    ):
        nom = table_noms.get(identifiant)
        if nom is not None:
            noms[str(identifiant)] = nom
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
        noms=noms,
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
    lignes = resultat.all()

    # Task 12 : identifiants collectés sur toute la page avant toute
    # requête de résolution (voir docstring de module) — jamais une requête
    # par entrée.
    ids_par_entree = [_ids_references(ligne[0]) for ligne in lignes]
    tous_utilisateurs: set[uuid.UUID] = set()
    tous_chantiers: set[uuid.UUID] = set()
    tous_fournisseurs: set[uuid.UUID] = set()
    for utilisateurs_ids, chantiers_ids, fournisseurs_ids in ids_par_entree:
        tous_utilisateurs |= utilisateurs_ids
        tous_chantiers |= chantiers_ids
        tous_fournisseurs |= fournisseurs_ids

    noms_utilisateurs = await _noms_par_id(
        session,
        Utilisateur.id,
        func.coalesce(Utilisateur.nom, Utilisateur.email),
        tous_utilisateurs,
    )
    noms_chantiers = await _noms_par_id(
        session, Chantier.id, Chantier.nom_canonique, tous_chantiers
    )
    noms_fournisseurs = await _noms_par_id(
        session, Fournisseur.id, Fournisseur.nom, tous_fournisseurs
    )

    return [
        _journal_lue(
            ligne, ids_entree, noms_utilisateurs, noms_chantiers, noms_fournisseurs
        )
        for ligne, ids_entree in zip(lignes, ids_par_entree, strict=True)
    ]
