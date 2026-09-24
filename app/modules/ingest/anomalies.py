"""Anomalies : génération idempotente, cycle de vie, lecture
(`ingest/anomalies.py`, L4-T8).

Persiste les sorties du moteur de règles pur (`app.modules.rules`, module
déjà commité, non modifié ici) : `synchroniser_anomalies` sera appelée par
`ingest.rapprochement.rapprocher_facture` (L4-T7 — Ruling R1 du contrôleur :
cette tâche passe avant le rapprochement et lui fournit sa dépendance) ainsi
que par les contrôles différés (`app.cli controles-differes`, L4-T11).
`lister_anomalies`/`compter_anomalies_hautes_ouvertes`/`traiter_anomalie`
seront consommées par `api/anomalies.py` (L4-T9).

Décisions du contrôleur (L4-T8) :
- `AnomaliePure` = `app.modules.rules.modeles.Anomalie` : `ingest` a le
  droit de l'importer (module pur, frontière déjà vérifiée par
  `tests/test_frontieres.py`) ; l'alias distingue cette dataclasse pure de
  l'`Anomalie` ORM d'`ingest/models.py`.
- Identité d'une anomalie (L4-D11, étendue par Ruling R13 de la tâche
  L4-T11) : `(regle, document_id, bloc_id, ligne_id, chantier_id,
  alias_id)`, garantie par l'index unique `NULLS NOT DISTINCT` de la
  migration 0007 (qui remplace celui de la migration 0006, sans
  `chantier_id`/`alias_id`). Extension nécessaire dès que ce module
  persiste des anomalies de suivi (R06, R14, R15, R16, `ingest/suivi.py`,
  L4-T11) : sans elle, deux chantiers silencieux (R16) ou deux alias en
  attente distincts (R14) partageraient tous l'identité `(leur regle, None,
  None, None)` et se confondraient en une seule anomalie — `chantier_id` et
  `alias_id` (`rules.modeles.Anomalie`, déjà portés par le module pur)
  lèvent l'ambiguïté. `synchroniser_anomalies` upsert sur cette clé : une
  anomalie `ouverte` existante voit `detail`/`gravite`/`article_id` mis à
  jour ; une anomalie `traitee`/`ignoree` n'est **jamais** touchée (L4-D12),
  qu'elle soit encore produite ou non.
- Anomalie levée (L4-D12) : une anomalie `ouverte` de la portée qui n'est
  plus produite par le rejeu est supprimée, avec un journal `anomalie_levee`
  (`utilisateur_id=NULL`, `avant = {regle, gravite, detail}`, `apres=None`).
- Portée (décision du contrôleur, **Ruling R8** — fix round 1 de la revue de
  cette tâche) : `portee_regles` est **obligatoire** dès qu'un balayage de
  suppression a lieu, c'est-à-dire à chaque appel (`ValueError` si absent
  ou vide, quel que soit `portee_document_id`). Le balayage ne considère
  donc **jamais** une règle qui n'a pas été effectivement recalculée par cet
  appel : sans cette contrainte, un rejeu de `rapprocher_facture` (qui ne
  recalcule que les règles de `evaluer_facture`, jamais R06/R14/R15/R16,
  L4-D14) supprimerait silencieusement une anomalie de suivi valide
  attachée à la même facture/bloc — constat de la revue (Important).
  `rapprocher_facture` (L4-T7) doit donc passer l'ensemble exact des règles
  que `evaluer_facture` peut produire (`R01, R02, R03, R04, R05, R07, R08,
  R09, R10, R11, R12, R13, R17`) ; les contrôles différés (L4-T11) passent
  `{R06, R14, R15, R16}`. Le balayage effectif est toujours « (`document_id`
  est la portée **ou** `bloc_id` appartient à cette facture, si
  `portee_document_id` est fourni) **ET** `regle` ∈ `portee_regles` » —
  `portee_document_id` seul (sans facture, pour la portée « suivi » du
  L4-T11) retire le premier facteur : la portée devient alors « toutes les
  anomalies ouvertes de ces règles », sans filtre de document.
- Règle des 90 jours (L4-D13) : au moment d'insérer une anomalie **neuve**
  (clé absente de la base) portant un `article_id`, si une anomalie de même
  règle et même article, dont le document appartient au même fournisseur,
  est `ignoree` avec `traitee_le >= now() - duree_ignorance_j`, l'insertion
  est sautée (l'anomalie existante n'est pas touchée). Ne s'applique jamais
  à la mise à jour d'une anomalie déjà `ouverte` (déjà exclue de la branche
  d'insertion) ni à une anomalie sans `article_id` (niveau bloc/document).
  Seuil lu par `referentiels.lire_parametre_decimal` (L3-D4).
- `synchroniser_anomalies` ne commite jamais (comme `referentiels
  .resoudre_chantier`/`rattacher_article`) : c'est l'appelant
  (`rapprocher_facture`, qui journalise déjà l'opération globale — aucune
  ligne de journal pour une simple création/mise à jour d'anomalie) qui
  décide du périmètre de la transaction. Elle renvoie le nombre d'anomalies
  `ouverte` de la portée après synchronisation — valeur absente de la fiche,
  décision du contrôleur : utile à l'appelant pour son propre journal
  (`rapprocher_facture`) et pour un retour de CLI, sans requête
  supplémentaire de sa part.
- `traiter_anomalie` est une action admin de premier niveau (comme
  `referentiels.valider_article`) : elle commite.
- `AnomalieLue.traitee_par` (comme `DocumentDetail.confirme_par`,
  `ingest/corrections.py`) porte le **nom** résolu de l'utilisateur, jamais
  son UUID brut — c'est la valeur affichée par le front (L4-T9/T10).
- Ruling R19 (fix round 2 de la tâche L4-T7) : le chantier d'une anomalie
  (`_requete_anomalies`, `lister_anomalies`) se résout par
  `CHANTIER_ID_RESOLU` = `COALESCE(Anomalie.chantier_id,
  BlocFacture.chantier_id, Document.chantier_id)` — la colonne
  `Anomalie.chantier_id` (migration 0007, portée d'une anomalie de suivi
  comme R16) n'était jamais lue avant ce correctif, laissant les anomalies
  de suivi sans chantier à l'écran et invisibles du filtre. La portée
  explicitement posée par la règle prime sur toute déduction depuis le bloc
  ou le document.
- `condition_regles_actives` (décision d'Ilane du 24/09/2026, `docs/dette
  .md` : contrôles de prix puis R06 désactivés) : masque toute anomalie dont
  la règle est dans `ingest.commun.regles_desactivees()` (R07/R08/R09 tant
  que `CONTROLE_PRIX_ACTIF` n'est pas actif, R06 tant que `CONTROLE_LIVRE_
  NON_FACTURE_ACTIF` n'est pas actif) — jamais détruite ni fermée
  (`rapprochement.rapprocher_facture`/`ingest.suivi.controles_differes` ne
  les passent plus à `synchroniser_anomalies` comme « recalculées », voir
  leurs docstrings), seulement absente de chaque lecture. Point unique,
  réutilisé par `_requete_anomalies`, `compter_anomalies_ouvertes`,
  `compter_anomalies_hautes_ouvertes` ainsi que `ingest.bilan._sous_requete_
  anomalies`/`_anomalies_par_ligne_et_bloc` et `ingest.comparaison_bl
  .comparer_bl` — jamais un filtre dupliqué par écran (`bilan`, tableau de
  bord, export CSV et compte « À régler » en héritent tous, puisqu'ils
  réutilisent ces mêmes fonctions). `traiter_anomalie` applique la même
  règle avant toute modification (constat mineur 1 de la revue des
  contrôles de prix) : une anomalie masquée est `AnomalieIntrouvable`
  (404), jamais un statut changé ni une ligne de journal. Le journal
  (`ingest/journal.py`) ne filtre jamais sur ce critère : il garde
  l'historique tel quel, décision explicite de la tâche.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import ColumnElement, Select, case, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.ingest.commun import regles_desactivees
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    Document,
    Fournisseur,
    Journal,
    Ligne,
    Utilisateur,
)
from app.modules.ingest.referentiels import lire_parametre_decimal
from app.modules.rules.modeles import Anomalie as AnomaliePure

CLE_DUREE_IGNORANCE_J = "duree_ignorance_j"
DUREE_IGNORANCE_DEFAUT = Decimal("90")

Categorie = Literal["bl", "prix", "quantites", "rattacher", "autre"]

# Catégorie d'un problème (revue finale de la refonte du front, constat
# SERVEUR-3) : **la seule** table règle -> catégorie de l'application. Elle
# fonde à la fois l'état d'un chantier (`ingest.tableau_de_bord`), le
# montant « en écart » du bilan (`ingest.bilan.REGLES_QUANTITE_OU_PRIX`,
# dérivé d'ici) et les filtres de l'écran « À régler » (champ `categorie`
# de `AnomalieLue`, lu tel quel par le front) -- avant ce correctif, trois
# tables différentes se contredisaient (une R05 rendait un chantier
# « Quantités à vérifier » sans jamais apparaître sous le filtre
# « Quantités »). Invariant vérifié par test : `prix | quantites` vaut
# exactement l'ancien `REGLES_QUANTITE_OU_PRIX` (R03 à R09, décision L5-T1,
# `en_ecart` inchangé). Toute règle absente de la table est « autre » :
# R10-R13 (contrôles de document, doublon, avoir), R15 (quantités jamais
# confirmées par l'équipe : un défaut de confirmation sur le bon, sans
# montant, jamais un écart entre livré et facturé), R16 (chantier sans
# dépôt récent : un rappel sur le chantier, pas une livraison sans bon) et
# R17 (conditionnement inhabituel, déjà exclu d'`en_ecart` par la décision
# L5-T1 : « ce ne sont pas des écarts de quantité ou de prix sur une
# ligne »).
CATEGORIES_REGLE: dict[str, Categorie] = {
    "R01": "bl",
    "R02": "bl",
    "R03": "quantites",
    "R04": "quantites",
    "R05": "quantites",
    "R06": "quantites",
    "R07": "prix",
    "R08": "prix",
    "R09": "prix",
    "R14": "rattacher",
}


def categorie_regle(regle: str) -> Categorie:
    """Catégorie d'une règle (voir `CATEGORIES_REGLE`), « autre » pour
    toute règle absente de la table, jamais une exception."""
    return CATEGORIES_REGLE.get(regle, "autre")


def regles_de_categorie(*categories: Categorie) -> frozenset[str]:
    """Règles rangées dans l'une des `categories` -- dérivé de
    `CATEGORIES_REGLE`, jamais une seconde liste écrite à la main."""
    return frozenset(
        regle
        for regle, categorie in CATEGORIES_REGLE.items()
        if categorie in categories
    )


# Transitions autorisées par le cycle de vie (L4-D15) : depuis `ouverte`
# uniquement, vers l'un de ces deux statuts.
_STATUTS_TRANSITION: tuple[str, ...] = ("traitee", "ignoree")
_ACTION_JOURNAL_PAR_STATUT: dict[str, str] = {
    "traitee": "anomalie_traitee",
    "ignoree": "anomalie_ignoree",
}

COMMENTAIRE_LONGUEUR_MIN = 1
COMMENTAIRE_LONGUEUR_MAX = 500

# Ordre d'affichage des gravités (CDC §4.6, décision du contrôleur pour
# `lister_anomalies`) : haute, moyenne, basse, puis `created_at` croissant.
_ORDRE_GRAVITE = case(
    (Anomalie.gravite == "haute", 0),
    (Anomalie.gravite == "moyenne", 1),
    (Anomalie.gravite == "basse", 2),
    else_=3,
)

# Chantier effectif d'une anomalie (Ruling R19, fix round 2 de L4-T7) :
# `Anomalie.chantier_id` -- portée explicitement posée par une règle de
# suivi (ex. R16 « chantier silencieux »), ajoutée par la migration 0007 --
# prime sur celui du bloc, qui prime sur celui du document (un
# BL/enlèvement porte son propre `chantier_id`, une facture n'en porte pas
# directement, CDC §6) : une valeur explicite n'est jamais une déduction.
# Factorisé en une seule expression, partagée par `_requete_anomalies` (ce
# qu'affiche l'écran Anomalies) et `lister_anomalies` (son filtre
# `chantier_id`) -- sinon l'écran afficherait un chantier sur lequel il
# refuse de filtrer.
CHANTIER_ID_RESOLU = func.coalesce(
    Anomalie.chantier_id, BlocFacture.chantier_id, Document.chantier_id
)


def _cle_anomalie(
    regle: str,
    document_id: uuid.UUID | None,
    bloc_id: uuid.UUID | None,
    ligne_id: uuid.UUID | None,
    chantier_id: uuid.UUID | None,
    alias_id: uuid.UUID | None,
) -> tuple[
    str,
    uuid.UUID | None,
    uuid.UUID | None,
    uuid.UUID | None,
    uuid.UUID | None,
    uuid.UUID | None,
]:
    """Identité d'une anomalie (L4-D11, étendue par Ruling R13), utilisée
    aussi bien pour une `AnomaliePure` fraîchement produite que pour une
    ligne déjà en base."""
    return (regle, document_id, bloc_id, ligne_id, chantier_id, alias_id)


async def _trouver_par_cle(
    session: AsyncSession,
    regle: str,
    document_id: uuid.UUID | None,
    bloc_id: uuid.UUID | None,
    ligne_id: uuid.UUID | None,
    chantier_id: uuid.UUID | None,
    alias_id: uuid.UUID | None,
) -> Anomalie | None:
    """Une anomalie par sa clé d'identité (L4-D11, Ruling R13) :
    `is_not_distinct_from` reproduit en Python la sémantique `NULLS NOT
    DISTINCT` de l'index unique de la migration 0007 (deux `NULL` sont
    considérés égaux)."""
    return (
        await session.execute(
            select(Anomalie).where(
                Anomalie.regle == regle,
                Anomalie.document_id.is_not_distinct_from(document_id),
                Anomalie.bloc_id.is_not_distinct_from(bloc_id),
                Anomalie.ligne_id.is_not_distinct_from(ligne_id),
                Anomalie.chantier_id.is_not_distinct_from(chantier_id),
                Anomalie.alias_id.is_not_distinct_from(alias_id),
            )
        )
    ).scalar_one_or_none()


async def _bloquee_par_ignorance(
    session: AsyncSession,
    *,
    regle: str,
    article_id: uuid.UUID,
    fournisseur_id: uuid.UUID,
    seuil: datetime,
) -> bool:
    """`True` si une anomalie de même règle et même article, dont le
    document appartient à `fournisseur_id`, est `ignoree` depuis moins de
    `duree_ignorance_j` (L4-D13)."""
    resultat = await session.execute(
        select(Anomalie.id)
        .join(Document, Document.id == Anomalie.document_id)
        .where(
            Anomalie.regle == regle,
            Anomalie.article_id == article_id,
            Anomalie.statut == "ignoree",
            Anomalie.traitee_le.is_not(None),
            Anomalie.traitee_le >= seuil,
            Document.fournisseur_id == fournisseur_id,
        )
        .limit(1)
    )
    return resultat.first() is not None


def _conditions_portee(
    portee_document_id: uuid.UUID | None,
    portee_regles: Sequence[str],
) -> list[Any]:
    """Conditions SQL de la portée (voir docstring de module, Ruling R8) :
    `statut = 'ouverte'` toujours, `regle` ∈ `portee_regles` toujours (le
    balayage ne considère jamais une règle qui n'a pas été recalculée),
    plus la portée facture (`document_id` ou bloc de cette facture) quand
    `portee_document_id` est fourni. `portee_regles` est déjà validé non
    vide par l'appelant (`synchroniser_anomalies`)."""
    conditions: list[Any] = [
        Anomalie.statut == "ouverte",
        Anomalie.regle.in_(tuple(portee_regles)),
    ]
    if portee_document_id is not None:
        blocs_de_la_facture = select(BlocFacture.id).where(
            BlocFacture.facture_id == portee_document_id
        )
        conditions.append(
            or_(
                Anomalie.document_id == portee_document_id,
                Anomalie.bloc_id.in_(blocs_de_la_facture.scalar_subquery()),
            )
        )
    return conditions


async def synchroniser_anomalies(
    session: AsyncSession,
    *,
    anomalies: Sequence[AnomaliePure],
    portee_document_id: uuid.UUID | None = None,
    portee_regles: Sequence[str] | None = None,
) -> int:
    """Persiste `anomalies` (upsert par clé d'identité, L4-D11) et lève les
    anomalies `ouverte` de la portée qui ne sont plus produites (L4-D12).

    `portee_regles` est **obligatoire** (Ruling R8, fix round 1) : le
    balayage de suppression ne doit jamais considérer une règle qui n'a pas
    été effectivement recalculée par cet appel (voir docstring de module).
    L'appelant passe l'ensemble exact des règles qu'il vient de
    recalculer — jamais un sous-ensemble arbitraire.

    Ne commite jamais (voir docstring de module) : c'est l'appelant qui
    décide du périmètre de la transaction. Renvoie le nombre d'anomalies
    `ouverte` de la portée après synchronisation.
    """
    if not portee_regles:
        raise ValueError(
            "synchroniser_anomalies : portee_regles requis (le balayage de "
            "suppression doit être borné aux règles réellement recalculées, "
            "Ruling R8)"
        )

    cles_produites = {
        _cle_anomalie(
            a.regle, a.document_id, a.bloc_id, a.ligne_id, a.chantier_id, a.alias_id
        )
        for a in anomalies
    }

    duree_ignorance = await lire_parametre_decimal(
        session, CLE_DUREE_IGNORANCE_J, DUREE_IGNORANCE_DEFAUT
    )
    # `duree_ignorance_j` est un nombre entier de jours (comme les autres
    # délais de `rules.modeles.Parametres`, ex. `delai_alias_non_resolu_h`) :
    # `int(...)` plutôt que `float(...)` (règle globale « Decimal, jamais
    # float », fix round 1).
    seuil_ignorance = datetime.now(UTC) - timedelta(days=int(duree_ignorance))

    # Fournisseur de chaque document impliqué (une seule requête), pour la
    # règle des 90 jours ci-dessous.
    document_ids = {a.document_id for a in anomalies if a.document_id is not None}
    fournisseur_par_document: dict[uuid.UUID, uuid.UUID | None] = {}
    if document_ids:
        lignes_documents = await session.execute(
            select(Document.id, Document.fournisseur_id).where(
                Document.id.in_(document_ids)
            )
        )
        fournisseur_par_document = {
            document_id: fournisseur_id
            for document_id, fournisseur_id in lignes_documents.all()
        }

    for anomalie_pure in anomalies:
        existante = await _trouver_par_cle(
            session,
            anomalie_pure.regle,
            anomalie_pure.document_id,
            anomalie_pure.bloc_id,
            anomalie_pure.ligne_id,
            anomalie_pure.chantier_id,
            anomalie_pure.alias_id,
        )
        if existante is not None:
            if existante.statut == "ouverte":
                existante.gravite = anomalie_pure.gravite.value
                existante.detail = dict(anomalie_pure.detail)
                existante.article_id = anomalie_pure.article_id
            # `traitee`/`ignoree` : jamais touchée (L4-D12), qu'elle soit
            # encore produite ou non.
            continue

        if anomalie_pure.article_id is not None:
            fournisseur_id = (
                fournisseur_par_document.get(anomalie_pure.document_id)
                if anomalie_pure.document_id is not None
                else None
            )
            if fournisseur_id is not None and await _bloquee_par_ignorance(
                session,
                regle=anomalie_pure.regle,
                article_id=anomalie_pure.article_id,
                fournisseur_id=fournisseur_id,
                seuil=seuil_ignorance,
            ):
                continue

        session.add(
            Anomalie(
                regle=anomalie_pure.regle,
                gravite=anomalie_pure.gravite.value,
                document_id=anomalie_pure.document_id,
                bloc_id=anomalie_pure.bloc_id,
                ligne_id=anomalie_pure.ligne_id,
                article_id=anomalie_pure.article_id,
                chantier_id=anomalie_pure.chantier_id,
                alias_id=anomalie_pure.alias_id,
                detail=dict(anomalie_pure.detail),
                statut="ouverte",
            )
        )

    await session.flush()

    conditions_portee = _conditions_portee(portee_document_id, portee_regles)
    candidates = (
        (await session.execute(select(Anomalie).where(*conditions_portee)))
        .scalars()
        .all()
    )
    for anomalie_db in candidates:
        cle = _cle_anomalie(
            anomalie_db.regle,
            anomalie_db.document_id,
            anomalie_db.bloc_id,
            anomalie_db.ligne_id,
            anomalie_db.chantier_id,
            anomalie_db.alias_id,
        )
        if cle in cles_produites:
            continue
        session.add(
            Journal(
                utilisateur_id=None,
                action="anomalie_levee",
                cible_table="anomalie",
                cible_id=str(anomalie_db.id),
                avant={
                    "regle": anomalie_db.regle,
                    "gravite": anomalie_db.gravite,
                    "detail": anomalie_db.detail,
                },
                apres=None,
            )
        )
        await session.delete(anomalie_db)

    await session.flush()

    return (
        await session.execute(
            select(func.count()).select_from(Anomalie).where(*conditions_portee)
        )
    ).scalar_one()


# --------------------------------------------------------------------------
# Lecture (`GET /api/anomalies`, L4-T9)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AnomalieLue:
    """Une anomalie, telle qu'exposée à l'API (L4-T9) : document source,
    bloc, chantier et fournisseur résolus ici (une seule requête avec
    jointures), jamais recalculés côté front. La phrase de justification
    elle-même reste construite côté front à partir de `detail` (L4-D17,
    même mécanique que `lib/motifs.ts`)."""

    id: uuid.UUID
    regle: str
    gravite: str
    statut: str
    detail: dict[str, Any]
    cree_le: datetime
    traitee_le: datetime | None
    traitee_par: str | None
    commentaire: str | None
    document_id: uuid.UUID | None
    numero_interne: int | None
    type: str | None
    numero: str | None
    bloc_id: uuid.UUID | None
    numero_bl: str | None
    chantier_id: uuid.UUID | None
    chantier: str | None
    fournisseur_id: uuid.UUID | None
    fournisseur: str | None
    bl_document_id: uuid.UUID | None
    categorie: Categorie


class AnomalieIntrouvable(Exception):
    """Aucune anomalie avec cet identifiant."""


class TransitionInterdite(Exception):
    """L'anomalie est déjà `traitee` ou `ignoree` (transition refusée)."""


def condition_regles_actives() -> ColumnElement[bool]:
    """Masque les anomalies dont la règle est désactivée côté serveur --
    voir le docstring de module (décision d'Ilane du 24/09/2026). `true()`
    (jamais de filtre `IN` avec une liste vide, dont la portabilité SQL
    n'est pas garantie) quand `regles_desactivees()` est vide, c'est-à-dire
    la quasi-totalité du temps une fois le drapeau réactivé."""
    exclues = regles_desactivees()
    if not exclues:
        return true()
    return Anomalie.regle.not_in(tuple(exclues))


def _requete_anomalies(*conditions: Any) -> Select[Any]:
    """Requête commune à `lister_anomalies` et à la relecture d'une
    anomalie après `traiter_anomalie` (décision du contrôleur : jamais
    dupliquer les jointures). Chantier résolu par `CHANTIER_ID_RESOLU`
    (Ruling R19, fix round 2 de L4-T7) : `Anomalie.chantier_id` d'abord,
    sinon le bloc, sinon le document lui-même. `condition_regles_actives()`
    masque les anomalies des règles désactivées (voir son docstring) --
    point unique pour tous les appelants de cette requête."""
    traitee_par_alias = aliased(Utilisateur)
    return (
        select(
            Anomalie,
            Document.numero_interne,
            Document.type,
            Document.numero,
            BlocFacture.numero_bl,
            BlocFacture.bl_document_id,
            CHANTIER_ID_RESOLU.label("chantier_id"),
            Chantier.nom_canonique,
            Document.fournisseur_id,
            Fournisseur.nom,
            func.coalesce(traitee_par_alias.nom, traitee_par_alias.email),
        )
        .outerjoin(Document, Document.id == Anomalie.document_id)
        .outerjoin(BlocFacture, BlocFacture.id == Anomalie.bloc_id)
        .outerjoin(Chantier, Chantier.id == CHANTIER_ID_RESOLU)
        .outerjoin(Fournisseur, Fournisseur.id == Document.fournisseur_id)
        .outerjoin(traitee_par_alias, traitee_par_alias.id == Anomalie.traitee_par)
        .where(condition_regles_actives(), *conditions)
    )


def _anomalie_lue(ligne: Any) -> AnomalieLue:
    (
        anomalie,
        numero_interne,
        type_document,
        numero_document,
        numero_bl,
        bl_document_id,
        chantier_id,
        nom_chantier,
        fournisseur_id,
        nom_fournisseur,
        nom_traiteur,
    ) = ligne
    return AnomalieLue(
        id=anomalie.id,
        regle=anomalie.regle,
        gravite=anomalie.gravite,
        statut=anomalie.statut,
        detail=anomalie.detail,
        cree_le=anomalie.created_at,
        traitee_le=anomalie.traitee_le,
        traitee_par=nom_traiteur,
        commentaire=anomalie.commentaire,
        document_id=anomalie.document_id,
        numero_interne=numero_interne,
        type=type_document,
        numero=numero_document,
        bloc_id=anomalie.bloc_id,
        numero_bl=numero_bl,
        chantier_id=chantier_id,
        chantier=nom_chantier,
        fournisseur_id=fournisseur_id,
        fournisseur=nom_fournisseur,
        bl_document_id=bl_document_id,
        categorie=categorie_regle(anomalie.regle),
    )


LIMITE_ANOMALIES_DEFAUT = 100


def condition_anomalies_du_bl(document_id: uuid.UUID) -> ColumnElement[bool]:
    """Anomalies qui concernent un BL (ou un enlèvement), au sens large
    (revue finale de la refonte du front, constats SERVEUR-4 et LIENS-1) :
    portées par le bon lui-même (`document_id`, ex. R11/R15), par l'un des
    blocs de facture qui le citent (`bloc_id`, ex. R01/R02/R12) ou par une
    ligne de l'un ou de l'autre (`ligne_id` : une ligne du bon, ex. R06, ou
    une ligne de facture de ces blocs, appariée ou non, ex. R03-R09/R05).

    Tous les blocs qui citent ce bon comptent (pas seulement le premier) --
    un bon facturé deux fois porte son R12 sur le bloc de la seconde facture
    -- sauf ceux d'une facture archivée (même garde que le bilan et le
    rapprochement : `type == "facture"`, `statut != "archive"`). Une seule
    définition, partagée par `comparaison_bl.comparer_bl` (`nb_problemes`)
    et par le filtre `bl_document_id` de `lister_anomalies` (écran « À
    régler » ouvert depuis la page du bon) : le nombre annoncé sur le bon et
    la liste ouverte par « Régler les problèmes » ne peuvent plus diverger.
    Condition SQL pure (sous-requêtes non corrélées), à combiner avec un
    filtre de statut par l'appelant."""
    facture = aliased(Document)
    blocs_du_bl = (
        select(BlocFacture.id)
        .join(facture, facture.id == BlocFacture.facture_id)
        .where(
            BlocFacture.bl_document_id == document_id,
            facture.type == "facture",
            facture.statut != "archive",
        )
    )
    lignes_concernees = select(Ligne.id).where(
        or_(Ligne.document_id == document_id, Ligne.bloc_id.in_(blocs_du_bl))
    )
    return or_(
        Anomalie.document_id == document_id,
        Anomalie.bloc_id.in_(blocs_du_bl),
        Anomalie.ligne_id.in_(lignes_concernees),
    )


async def lister_anomalies(
    session: AsyncSession,
    *,
    regle: str | None = None,
    gravite: str | None = None,
    statut: str | None = None,
    bloc_id: uuid.UUID | None = None,
    chantier_id: uuid.UUID | None = None,
    fournisseur_id: uuid.UUID | None = None,
    bl_document_id: uuid.UUID | None = None,
    depuis: datetime | None = None,
    jusqu_a: datetime | None = None,
    ids: Collection[uuid.UUID] | None = None,
    limite: int = LIMITE_ANOMALIES_DEFAUT,
) -> list[AnomalieLue]:
    """Liste des anomalies (`GET /api/anomalies`, L4-T9), filtres
    combinables, triée par gravité (haute, moyenne, basse) puis
    `created_at` croissant (décision du contrôleur). `limite` est bornée par
    l'appelant (le routeur), comme `ingest.lecture.lister_documents`.

    Le filtre `chantier_id` porte sur `CHANTIER_ID_RESOLU` (Ruling R19,
    fix round 2 de L4-T7) -- exactement la même expression que celle
    affichée par `_requete_anomalies`, sinon l'écran montrerait un chantier
    sur lequel il refuse de filtrer.

    `ids` (correction de revue, refonte front T2) : restreint aux
    identifiants donnés (`Anomalie.id.in_(...)`), pour un appelant qui a
    déjà déterminé la portée exacte des anomalies à lire par une autre
    requête (ex. `ingest.tableau_de_bord`, qui réutilise
    `ingest.bilan._sous_requete_anomalies` pour ne jamais recalculer
    divergemment le périmètre "anomalies du mois") -- combinable avec les
    autres filtres, qui restent tous optionnels.

    `bl_document_id` (revue finale de la refonte du front, constat
    LIENS-1) : restreint aux anomalies qui concernent ce bon, au sens de
    `condition_anomalies_du_bl` -- exactement le périmètre du nombre de
    problèmes annoncé par la page du bon."""
    conditions: list[Any] = []
    if regle is not None:
        conditions.append(Anomalie.regle == regle)
    if gravite is not None:
        conditions.append(Anomalie.gravite == gravite)
    if statut is not None:
        conditions.append(Anomalie.statut == statut)
    if bloc_id is not None:
        conditions.append(Anomalie.bloc_id == bloc_id)
    if chantier_id is not None:
        conditions.append(chantier_id == CHANTIER_ID_RESOLU)
    if fournisseur_id is not None:
        conditions.append(Document.fournisseur_id == fournisseur_id)
    if bl_document_id is not None:
        conditions.append(condition_anomalies_du_bl(bl_document_id))
    if depuis is not None:
        conditions.append(Anomalie.created_at >= depuis)
    if jusqu_a is not None:
        conditions.append(Anomalie.created_at <= jusqu_a)
    if ids is not None:
        conditions.append(Anomalie.id.in_(tuple(ids)))

    resultat = await session.execute(
        _requete_anomalies(*conditions)
        .order_by(_ORDRE_GRAVITE, Anomalie.created_at.asc())
        .limit(limite)
    )
    return [_anomalie_lue(ligne) for ligne in resultat.all()]


async def compter_anomalies_ouvertes(session: AsyncSession) -> tuple[int, int]:
    """`(toutes, de gravité haute)` parmi les anomalies `ouverte`, tous mois
    confondus -- exactement les lignes que renverrait `lister_anomalies(
    statut="ouverte")` sans plafond (`_requete_anomalies` n'a que des
    jointures externes, qui ne retirent ni ne dupliquent aucune anomalie).
    Sert au compte unique des problèmes « à régler » (`ingest.a_traiter
    .compter_problemes_a_regler`, revue finale de la refonte du front).
    `condition_regles_actives()` masque les règles désactivées, même
    principe que `_requete_anomalies`."""
    resultat = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Anomalie.gravite == "haute"),
            )
            .select_from(Anomalie)
            .where(condition_regles_actives(), Anomalie.statut == "ouverte")
        )
    ).one()
    return int(resultat[0]), int(resultat[1])


async def compter_anomalies_hautes_ouvertes(session: AsyncSession) -> int:
    """Nombre d'anomalies `ouverte` de gravité `haute` (section « anomalies
    ouvertes de gravité haute » de l'écran « À traiter », L4-D18).
    `condition_regles_actives()` masque les règles désactivées, même
    principe que `_requete_anomalies`."""
    return (
        await session.execute(
            select(func.count())
            .select_from(Anomalie)
            .where(
                condition_regles_actives(),
                Anomalie.statut == "ouverte",
                Anomalie.gravite == "haute",
            )
        )
    ).scalar_one()


# --------------------------------------------------------------------------
# Cycle de vie (`POST /api/anomalies/{id}/traitement`, L4-D15)
# --------------------------------------------------------------------------


async def traiter_anomalie(
    session: AsyncSession,
    anomalie_id: uuid.UUID,
    *,
    statut: str,
    commentaire: str,
    auteur_id: uuid.UUID,
) -> AnomalieLue:
    """Transition `ouverte` -> `traitee`/`ignoree` (L4-D15) : commentaire
    obligatoire (1 à 500 caractères après suppression des espaces de bord,
    même convention que `corrections._valeur_normalisee`), transition
    autorisée uniquement depuis `ouverte` (`TransitionInterdite` sinon).
    Journalise `anomalie_traitee`/`anomalie_ignoree` (avant/après statut et
    commentaire) et commite (action admin de premier niveau, comme
    `referentiels.valider_article`).

    `statut` invalide (ni `traitee` ni `ignoree`) : `ValueError` défensive —
    le contrat est déjà garanti côté route par le schéma Pydantic
    (L4-T9), jamais fait confiance aveuglément ici (même principe que
    `corrections.corriger_entete`).

    Anomalie d'une règle désactivée (constat mineur 1 de la revue des
    contrôles de prix, décision d'Ilane du 24/09/2026) : elle est masquée
    de toute lecture (`condition_regles_actives`, voir le docstring de
    module), donc traitée comme introuvable ici aussi -- `AnomalieIntrouvable`
    (404), **avant** toute modification, jamais un statut changé ni une
    ligne de journal pour une anomalie que l'écran ne montre plus.
    """
    if statut not in _STATUTS_TRANSITION:
        raise ValueError(f"statut invalide : {statut!r}")

    commentaire_normalise = commentaire.strip()
    if not (
        COMMENTAIRE_LONGUEUR_MIN
        <= len(commentaire_normalise)
        <= COMMENTAIRE_LONGUEUR_MAX
    ):
        raise ValueError("commentaire obligatoire (1 à 500 caractères)")

    anomalie = await session.get(Anomalie, anomalie_id)
    if anomalie is None or anomalie.regle in regles_desactivees():
        raise AnomalieIntrouvable(str(anomalie_id))
    if anomalie.statut != "ouverte":
        raise TransitionInterdite(str(anomalie_id))

    avant = {"statut": anomalie.statut, "commentaire": anomalie.commentaire}
    anomalie.statut = statut
    anomalie.commentaire = commentaire_normalise
    anomalie.traitee_par = auteur_id
    anomalie.traitee_le = datetime.now(UTC)

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action=_ACTION_JOURNAL_PAR_STATUT[statut],
            cible_table="anomalie",
            cible_id=str(anomalie_id),
            avant=avant,
            apres={"statut": statut, "commentaire": commentaire_normalise},
        )
    )
    await session.commit()

    ligne = (
        await session.execute(_requete_anomalies(Anomalie.id == anomalie_id))
    ).first()
    if ligne is None:
        # Incohérence impossible juste après le commit ci-dessus (défensif,
        # même principe que les gardes similaires de `corrections.py`).
        raise AnomalieIntrouvable(str(anomalie_id))
    return _anomalie_lue(ligne)
