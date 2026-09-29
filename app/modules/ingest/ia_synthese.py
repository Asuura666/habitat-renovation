"""Synthèse hebdomadaire des commentaires de lignes, actions à cocher et vue
de l'accueil (`ingest/ia_synthese.py`, T4, phase 4 IA — spec §4).

Orchestrateur (comme le reste d'`ingest`) : ce module lit les commentaires
(`ingest.commentaires.Commentaire`), construit le texte envoyé à l'IA,
l'interroge via `ingest.opencode.interroger` (seul point d'entrée réseau vers
l'IA du dépôt), garde la réponse via `extract.reponses_ia.lire_synthese`
(module pur), puis écrit `SyntheseCommentaires`/`SyntheseAction` et le
journal (`synthese_generee`). Il expose aussi la lecture pour l'accueil
(`vue_accueil`) et le cochage des actions (`marquer_action`), consommés par
`api/ia.py` (T4) puis l'écran (T5).

Minimisation des données envoyées à l'IA (§4.2, rappel CDC « l'IA extrait et
normalise, elle ne décide jamais ») : jamais le nom de l'auteur d'un
commentaire, le chantier ni le client — seulement une référence `[cN]`, le
jour (jamais une date complète avec l'année), le nom du fournisseur, le
numéro du bon et le libellé de la ligne commentée. `_texte_synthese` est une
fonction pure du module (aucune dépendance SQLAlchemy), testée en propre sur
des `_CommentaireEnvoye` construits à la main.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as heure
from typing import Any, Literal

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.extract.reponses_ia import (
    SCHEMA_SYNTHESE,
    ReponseIAInvalide,
    SyntheseLue,
    lire_synthese,
)
from app.modules.ingest.models import (
    Commentaire,
    Document,
    Fournisseur,
    Journal,
    SyntheseAction,
    SyntheseCommentaires,
    Utilisateur,
)
from app.modules.ingest.opencode import ErreurIA, IAIndisponible, ia_active, interroger

# Plafonds du §4.2/§4.3 de la spec (jamais dépassés, quelle que soit la
# réponse de l'IA -- `lire_synthese`, module pur, applique déjà `_ACTIONS_MAX`
# côté lecture ; celui-ci borne ce qui part *vers* l'IA).
_COMMENTAIRES_MAX = 200
_ENCORE_A_FAIRE_MAX = 20
_RESUME_VIDE = "Aucun commentaire cette semaine."

_JOURS_FR = (
    "lundi",
    "mardi",
    "mercredi",
    "jeudi",
    "vendredi",
    "samedi",
    "dimanche",
)

_CONSIGNE_SYNTHESE = (
    "Voici les commentaires laissés cette semaine par l'équipe sur des "
    "lignes de bons de livraison. Résume-les en quelques phrases simples "
    "pour le dirigeant, puis propose au plus dix actions concrètes à "
    "mener ; chaque action cite, sans crochets (c1, c2, ...), les "
    "références des commentaires sur lesquels elle s'appuie. Tu ne décides "
    "rien : un humain choisira."
)


# --------------------------------------------------------------------------
# Semaine (heure de Paris)
# --------------------------------------------------------------------------


def semaine_de(jour: date) -> tuple[date, date]:
    """Lundi et dimanche de la semaine civile parisienne contenant `jour`."""
    lundi = jour - timedelta(days=jour.weekday())
    return lundi, lundi + timedelta(days=6)


def derniere_semaine_complete(maintenant: datetime) -> date:
    """Lundi de la semaine précédant celle de `maintenant`, heure de Paris
    (brief T4) -- `maintenant` peut être dans n'importe quel fuseau
    (`datetime.now(UTC)` côté CLI), converti ici avant de déterminer le jour
    civil parisien."""
    aujourd_hui_paris = maintenant.astimezone(FUSEAU_PARIS).date()
    lundi_courant, _ = semaine_de(aujourd_hui_paris)
    return lundi_courant - timedelta(days=7)


def _bornes_semaine_paris(semaine_debut: date) -> tuple[datetime, datetime]:
    """Instants (tz-aware) de début (lundi 00:00 inclus) et de fin (lundi
    suivant 00:00 exclu) d'une semaine civile parisienne -- mêmes bornes que
    `opencode._debut_jour_paris`, ici sur sept jours plutôt qu'un."""
    debut = datetime.combine(semaine_debut, heure.min, tzinfo=FUSEAU_PARIS)
    return debut, debut + timedelta(days=7)


# --------------------------------------------------------------------------
# Résultat de `generer_synthese`
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultatSynthese:
    """Résultat d'un passage de `generer_synthese` (un par appel de
    `python -m app.cli synthese-commentaires`, brief T4)."""

    statut: Literal["creee", "deja_faite", "vide", "ia_eteinte", "echec"]
    semaine_debut: date
    nb_commentaires: int = 0
    nb_actions: int = 0
    erreur: str | None = None


# --------------------------------------------------------------------------
# Texte envoyé à l'IA (pur, testé en propre)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _CommentaireEnvoye:
    """Un commentaire tel qu'il part vers l'IA (§4.2) -- jamais l'auteur, le
    chantier ni le client, aucun identifiant : seulement une référence
    `[cN]`, le jour, le fournisseur, le numéro du bon et le libellé de la
    ligne. Construit par `generer_synthese`, consommé par `_texte_synthese`."""

    reference: str
    jour: date
    fournisseur: str
    numero_bon: str | None
    ligne_libelle: str
    texte: str


def _texte_synthese(commentaires: Sequence[_CommentaireEnvoye], nb_total: int) -> str:
    """Texte envoyé à l'agent `habitat-synthese` (brief T4, étape 7) :
    consigne fixe, puis une ligne par commentaire du plus ancien au plus
    récent (déjà l'ordre attendu de `commentaires`). Une phrase de troncature
    est ajoutée quand `nb_total` (le nombre réel de commentaires de la
    semaine) dépasse le nombre envoyé (`_COMMENTAIRES_MAX` au plus)."""
    lignes = [_CONSIGNE_SYNTHESE]
    if nb_total > len(commentaires):
        lignes.append(
            f"{nb_total} commentaires cette semaine ; "
            f"les {len(commentaires)} plus récents ci-dessous."
        )
    for commentaire in commentaires:
        jour_libelle = (
            f"{_JOURS_FR[commentaire.jour.weekday()]} {commentaire.jour:%d/%m}"
        )
        numero_bon = commentaire.numero_bon or "inconnu"
        lignes.append(
            f"[{commentaire.reference}] {jour_libelle} — {commentaire.fournisseur} — "
            f"bon {numero_bon} — ligne « {commentaire.ligne_libelle} » : "
            f"{commentaire.texte}"
        )
    return "\n".join(lignes)


# --------------------------------------------------------------------------
# Chargement des commentaires d'une semaine -- factorisé (tâche LABO,
# Laboratoire IA) pour être partagé par `generer_synthese` (production) et
# `ingest.ia_labo.lancer_essai_synthese` (essai) : même sélection, même
# numérotation `c1..cN`, jamais deux implémentations.
# --------------------------------------------------------------------------


async def _commentaires_de_la_semaine(
    session: AsyncSession, debut_dt: datetime, fin_dt: datetime
) -> tuple[list[_CommentaireEnvoye], dict[str, Commentaire], int]:
    """Commentaires d'une semaine (bornes déjà calculées, `_bornes_semaine_
    paris`), prêts pour `_texte_synthese` : `nb_total` est le nombre réel de
    commentaires de la semaine (peut dépasser `_COMMENTAIRES_MAX`, auquel cas
    seuls les plus récents figurent dans la liste renvoyée -- `_texte_synthese`
    le signale). Listes vides et `nb_total=0` si la semaine n'a aucun
    commentaire, sans requête supplémentaire."""
    nb_total = (
        await session.execute(
            select(func.count())
            .select_from(Commentaire)
            .where(Commentaire.created_at >= debut_dt, Commentaire.created_at < fin_dt)
        )
    ).scalar_one()
    if nb_total == 0:
        return [], {}, 0

    lignes_recentes = (
        await session.execute(
            select(Commentaire, Document.numero, Fournisseur.nom)
            .join(Document, Document.id == Commentaire.document_id)
            .outerjoin(Fournisseur, Fournisseur.id == Document.fournisseur_id)
            .where(Commentaire.created_at >= debut_dt, Commentaire.created_at < fin_dt)
            .order_by(Commentaire.created_at.desc())
            .limit(_COMMENTAIRES_MAX)
        )
    ).all()
    # Plus ancien au plus récent (numérotation c1..cN, brief T4 étape 4) :
    # la requête ci-dessus est triée en sens inverse pour que `LIMIT` garde
    # les plus récents plutôt que les plus anciens.
    lignes_db = list(reversed(lignes_recentes))

    commentaires_envoyes: list[_CommentaireEnvoye] = []
    commentaire_par_reference: dict[str, Commentaire] = {}
    for indice, (commentaire, numero_bon, fournisseur_nom) in enumerate(
        lignes_db, start=1
    ):
        reference = f"c{indice}"
        commentaire_par_reference[reference] = commentaire
        commentaires_envoyes.append(
            _CommentaireEnvoye(
                reference=reference,
                jour=commentaire.created_at.astimezone(FUSEAU_PARIS).date(),
                fournisseur=fournisseur_nom or "fournisseur inconnu",
                numero_bon=numero_bon,
                ligne_libelle=commentaire.ligne_libelle,
                texte=commentaire.texte,
            )
        )
    return commentaires_envoyes, commentaire_par_reference, nb_total


# --------------------------------------------------------------------------
# generer_synthese
# --------------------------------------------------------------------------


async def _enregistrer_synthese_vide(
    session: AsyncSession, semaine_debut: date, semaine_fin: date
) -> ResultatSynthese:
    """Écrit une synthèse `statut="vide"` (brief T4, étape 5) : aucun appel à
    l'IA. Course avec un passage concurrent sur la même semaine (brief T4,
    dernier paragraphe) : `IntegrityError` de l'unicité de `semaine_debut` ->
    `rollback` -> `deja_faite`, jamais propagée."""
    synthese = SyntheseCommentaires(
        semaine_debut=semaine_debut,
        semaine_fin=semaine_fin,
        statut="vide",
        resume=_RESUME_VIDE,
        nb_commentaires=0,
        modele=None,
    )
    session.add(synthese)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return ResultatSynthese(statut="deja_faite", semaine_debut=semaine_debut)

    session.add(
        Journal(
            utilisateur_id=None,
            action="synthese_generee",
            cible_table="synthese_commentaires",
            cible_id=str(synthese.id),
            avant=None,
            apres={
                "semaine_debut": semaine_debut.isoformat(),
                "semaine_fin": semaine_fin.isoformat(),
                "statut": "vide",
                "nb_commentaires": 0,
                "nb_actions": 0,
            },
        )
    )
    await session.commit()
    return ResultatSynthese(
        statut="vide", semaine_debut=semaine_debut, nb_commentaires=0
    )


async def _enregistrer_synthese_ok(
    session: AsyncSession,
    *,
    semaine_debut: date,
    semaine_fin: date,
    nb_commentaires: int,
    modele: str | None,
    synthese_lue: SyntheseLue,
    commentaire_par_reference: Mapping[str, Commentaire],
) -> ResultatSynthese:
    """Écrit la synthèse et ses actions (brief T4, étape 9). Même course
    qu'`_enregistrer_synthese_vide`, vérifiée sur le même `flush` (avant
    l'ajout des actions -- la seule contrainte pouvant échouer à ce point est
    l'unicité de `semaine_debut`, les autres ont déjà été gardées en amont
    -- `SyntheseLue`/`ActionLue`, `extract.reponses_ia`)."""
    synthese = SyntheseCommentaires(
        semaine_debut=semaine_debut,
        semaine_fin=semaine_fin,
        statut="ok",
        resume=synthese_lue.resume,
        nb_commentaires=nb_commentaires,
        modele=modele,
    )
    session.add(synthese)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return ResultatSynthese(statut="deja_faite", semaine_debut=semaine_debut)

    for ordre, action_lue in enumerate(synthese_lue.actions, start=1):
        commentaires_cites = [
            commentaire_par_reference[reference] for reference in action_lue.references
        ]
        document_ids: list[str] = []
        for commentaire in commentaires_cites:
            document_id = str(commentaire.document_id)
            if document_id not in document_ids:
                document_ids.append(document_id)
        session.add(
            SyntheseAction(
                synthese_id=synthese.id,
                ordre=ordre,
                texte=action_lue.texte,
                commentaire_ids=[str(c.id) for c in commentaires_cites],
                document_ids=document_ids,
            )
        )

    session.add(
        Journal(
            utilisateur_id=None,
            action="synthese_generee",
            cible_table="synthese_commentaires",
            cible_id=str(synthese.id),
            avant=None,
            apres={
                "semaine_debut": semaine_debut.isoformat(),
                "semaine_fin": semaine_fin.isoformat(),
                "statut": "ok",
                "nb_commentaires": nb_commentaires,
                "nb_actions": len(synthese_lue.actions),
            },
        )
    )
    await session.commit()
    return ResultatSynthese(
        statut="creee",
        semaine_debut=semaine_debut,
        nb_commentaires=nb_commentaires,
        nb_actions=len(synthese_lue.actions),
    )


async def generer_synthese(
    session: AsyncSession, http: httpx.AsyncClient, *, semaine_debut: date
) -> ResultatSynthese:
    """Génère (ou retrouve) la synthèse de la semaine commençant à
    `semaine_debut` (brief T4, étapes 1 à 9) :

    1. `semaine_debut` doit être un lundi (`ValueError` sinon) ;
    2. une synthèse existe déjà pour cette semaine -> `deja_faite` ;
    3. IA éteinte -> `ia_eteinte`, rien n'est écrit (même pour une semaine
       sans commentaire : la carte de l'accueil reste cachée tant que l'IA
       est éteinte) ;
    4. commentaires de la semaine (heure de Paris), avec le numéro du bon et
       le fournisseur de son document ;
    5. zéro commentaire -> `vide`, sans appel à l'IA ;
    6. plus de 200 commentaires -> les 200 plus récents seulement envoyés
       (`nb_commentaires` reste le compte réel) ;
    7. texte envoyé (`_texte_synthese`) ;
    8. `interroger` (usage `"synthese"`, agent `habitat-synthese`) ;
    9. réponse gardée par `lire_synthese`, puis écriture (`SyntheseCommentaires`
       + une `SyntheseAction` par action retenue, journal `synthese_generee`).

    Course entre deux passages simultanés sur la même semaine : gérée au
    moment de l'écriture (`_enregistrer_synthese_vide`/`_enregistrer_synthese_ok`),
    jamais ici."""
    if semaine_debut.weekday() != 0:
        raise ValueError(
            f"semaine_debut doit être un lundi (reçu {semaine_debut.isoformat()})"
        )

    deja_existante = (
        await session.execute(
            select(SyntheseCommentaires.id).where(
                SyntheseCommentaires.semaine_debut == semaine_debut
            )
        )
    ).scalar_one_or_none()
    if deja_existante is not None:
        return ResultatSynthese(statut="deja_faite", semaine_debut=semaine_debut)

    if not ia_active():
        return ResultatSynthese(statut="ia_eteinte", semaine_debut=semaine_debut)

    semaine_fin = semaine_debut + timedelta(days=6)
    debut_dt, fin_dt = _bornes_semaine_paris(semaine_debut)

    (
        commentaires_envoyes,
        commentaire_par_reference,
        nb_total,
    ) = await _commentaires_de_la_semaine(session, debut_dt, fin_dt)
    if nb_total == 0:
        return await _enregistrer_synthese_vide(session, semaine_debut, semaine_fin)

    texte_envoye = _texte_synthese(commentaires_envoyes, nb_total)

    try:
        reponse = await interroger(
            session,
            http,
            usage="synthese",
            agent="habitat-synthese",
            texte=texte_envoye,
            schema=SCHEMA_SYNTHESE,
        )
    except IAIndisponible as exc:
        if exc.raison == "eteinte":
            return ResultatSynthese(statut="ia_eteinte", semaine_debut=semaine_debut)
        return ResultatSynthese(
            statut="echec", semaine_debut=semaine_debut, erreur="plafond"
        )
    except ErreurIA as exc:
        return ResultatSynthese(
            statut="echec", semaine_debut=semaine_debut, erreur=exc.code
        )

    try:
        synthese_lue = lire_synthese(
            reponse.structure, commentaire_par_reference.keys()
        )
    except ReponseIAInvalide:
        return ResultatSynthese(
            statut="echec", semaine_debut=semaine_debut, erreur="reponse_invalide"
        )

    return await _enregistrer_synthese_ok(
        session,
        semaine_debut=semaine_debut,
        semaine_fin=semaine_fin,
        nb_commentaires=nb_total,
        modele=reponse.modele,
        synthese_lue=synthese_lue,
        commentaire_par_reference=commentaire_par_reference,
    )


# --------------------------------------------------------------------------
# Vue de l'accueil
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BonLie:
    """Un bon cité par une action, encore existant (brief T4 : « un bon
    supprimé disparaît de la liste »)."""

    document_id: uuid.UUID
    numero: str | None


@dataclass(frozen=True)
class ActionVue:
    """Une action de synthèse telle qu'affichée (dernière synthèse ou
    « encore à faire »)."""

    id: uuid.UUID
    texte: str
    semaine_debut: date
    faite_le: datetime | None
    faite_par: str | None
    bons: tuple[BonLie, ...]


@dataclass(frozen=True)
class SyntheseVue:
    """La dernière synthèse, avec ses actions."""

    id: uuid.UUID
    semaine_debut: date
    semaine_fin: date
    statut: str
    resume: str
    nb_commentaires: int
    actions: tuple[ActionVue, ...]


@dataclass(frozen=True)
class SyntheseAccueil:
    """Réponse de `vue_accueil` (`GET /api/ia/synthese`)."""

    ia_active: bool
    derniere: SyntheseVue | None
    encore_a_faire: tuple[ActionVue, ...]


async def _resoudre_bons(
    session: AsyncSession, document_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """`Document.numero` des documents encore existants parmi `document_ids`
    -- un identifiant absent du résultat correspond à un bon supprimé (brief
    T4 : « disparaît de la liste »). Une seule requête, jamais une par
    action (« pas de N+1 »)."""
    if not document_ids:
        return {}
    lignes = await session.execute(
        select(Document.id, Document.numero).where(Document.id.in_(document_ids))
    )
    return {document_id: numero for document_id, numero in lignes.all()}


async def _resoudre_noms(
    session: AsyncSession, utilisateur_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """`coalesce(nom, email)` des comptes parmi `utilisateur_ids` (même
    principe que `ingest.commentaires._nom_auteur`, en lot) -- un compte
    supprimé depuis reste simplement absent du résultat (`faite_par` devient
    alors `None` côté `ActionVue`, jamais une erreur)."""
    if not utilisateur_ids:
        return {}
    lignes = await session.execute(
        select(Utilisateur.id, func.coalesce(Utilisateur.nom, Utilisateur.email)).where(
            Utilisateur.id.in_(utilisateur_ids)
        )
    )
    return {utilisateur_id: nom for utilisateur_id, nom in lignes.all()}


def _construire_action_vue(
    action: SyntheseAction,
    *,
    semaine_debut: date,
    bons_par_document: Mapping[uuid.UUID, str | None],
    noms_par_utilisateur: Mapping[uuid.UUID, str],
) -> ActionVue:
    bons = tuple(
        BonLie(document_id=document_id, numero=bons_par_document[document_id])
        for document_id in (uuid.UUID(d) for d in action.document_ids)
        if document_id in bons_par_document
    )
    faite_par = (
        noms_par_utilisateur.get(action.faite_par)
        if action.faite_par is not None
        else None
    )
    return ActionVue(
        id=action.id,
        texte=action.texte,
        semaine_debut=semaine_debut,
        faite_le=action.faite_le,
        faite_par=faite_par,
        bons=bons,
    )


async def vue_accueil(session: AsyncSession) -> SyntheseAccueil:
    """Vue de la carte « Commentaires de la semaine » (brief T4, spec §4.5) :
    `derniere` synthèse (la plus grande `semaine_debut`) avec ses actions, et
    `encore_a_faire` : les actions non faites des *autres* synthèses (celles
    de `derniere` sont déjà rendues avec leur propre état), 20 au plus, les
    plus récentes d'abord. Deux requêtes en lot pour les bons et les noms des
    comptes (jamais une par action)."""
    derniere_db = (
        await session.execute(
            select(SyntheseCommentaires)
            .order_by(SyntheseCommentaires.semaine_debut.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    derniere_actions_db: list[SyntheseAction] = []
    if derniere_db is not None:
        derniere_actions_db = list(
            (
                await session.execute(
                    select(SyntheseAction)
                    .where(SyntheseAction.synthese_id == derniere_db.id)
                    .order_by(SyntheseAction.ordre)
                )
            )
            .scalars()
            .all()
        )

    filtres_encore: list[Any] = [SyntheseAction.faite_le.is_(None)]
    if derniere_db is not None:
        filtres_encore.append(SyntheseAction.synthese_id != derniere_db.id)
    encore_rows = (
        await session.execute(
            select(SyntheseAction, SyntheseCommentaires.semaine_debut)
            .join(
                SyntheseCommentaires,
                SyntheseCommentaires.id == SyntheseAction.synthese_id,
            )
            .where(*filtres_encore)
            .order_by(
                SyntheseCommentaires.semaine_debut.desc(), SyntheseAction.ordre.asc()
            )
            .limit(_ENCORE_A_FAIRE_MAX)
        )
    ).all()

    toutes_actions = derniere_actions_db + [action for action, _semaine in encore_rows]
    tous_document_ids = {
        uuid.UUID(document_id)
        for action in toutes_actions
        for document_id in action.document_ids
    }
    tous_faite_par_ids = {
        action.faite_par for action in toutes_actions if action.faite_par is not None
    }
    bons_par_document = await _resoudre_bons(session, tous_document_ids)
    noms_par_utilisateur = await _resoudre_noms(session, tous_faite_par_ids)

    derniere_vue: SyntheseVue | None = None
    if derniere_db is not None:
        derniere_vue = SyntheseVue(
            id=derniere_db.id,
            semaine_debut=derniere_db.semaine_debut,
            semaine_fin=derniere_db.semaine_fin,
            statut=derniere_db.statut,
            resume=derniere_db.resume,
            nb_commentaires=derniere_db.nb_commentaires,
            actions=tuple(
                _construire_action_vue(
                    action,
                    semaine_debut=derniere_db.semaine_debut,
                    bons_par_document=bons_par_document,
                    noms_par_utilisateur=noms_par_utilisateur,
                )
                for action in derniere_actions_db
            ),
        )

    encore_a_faire = tuple(
        _construire_action_vue(
            action,
            semaine_debut=semaine_debut,
            bons_par_document=bons_par_document,
            noms_par_utilisateur=noms_par_utilisateur,
        )
        for action, semaine_debut in encore_rows
    )

    return SyntheseAccueil(
        ia_active=ia_active(), derniere=derniere_vue, encore_a_faire=encore_a_faire
    )


# --------------------------------------------------------------------------
# marquer_action
# --------------------------------------------------------------------------


class ActionIntrouvable(Exception):
    """`SyntheseAction` inconnue (404, décision du contrôleur -- même
    principe que `LigneIntrouvable`)."""


async def marquer_action(
    session: AsyncSession,
    action_id: uuid.UUID,
    *,
    faite: bool,
    utilisateur_id: uuid.UUID,
) -> ActionVue:
    """Coche (`faite=True`) ou décoche (`faite=False`) une action (brief T4,
    décision D4). Idempotent : déjà dans l'état demandé -> rien n'est écrit,
    aucun journal (l'action est quand même relue et renvoyée telle quelle).
    Journal `synthese_action_faite`/`synthese_action_a_faire`, auteur =
    `utilisateur_id`."""
    action = await session.get(SyntheseAction, action_id)
    if action is None:
        raise ActionIntrouvable(str(action_id))

    synthese = await session.get(SyntheseCommentaires, action.synthese_id)
    if synthese is None:
        raise RuntimeError(
            "synthese_action sans synthese_commentaires (FK sans ON DELETE "
            "CASCADE manquant -- ne devrait jamais arriver)"
        )

    deja_dans_cet_etat = (action.faite_le is not None) == faite
    if not deja_dans_cet_etat:
        if faite:
            action.faite_le = datetime.now(UTC)
            action.faite_par = utilisateur_id
            action_journal = "synthese_action_faite"
        else:
            action.faite_le = None
            action.faite_par = None
            action_journal = "synthese_action_a_faire"
        session.add(
            Journal(
                utilisateur_id=utilisateur_id,
                action=action_journal,
                cible_table="synthese_action",
                cible_id=str(action.id),
                avant=None,
                apres={
                    "texte": action.texte,
                    "semaine_debut": synthese.semaine_debut.isoformat(),
                },
            )
        )
        await session.commit()
        await session.refresh(action)

    bons_par_document = await _resoudre_bons(
        session, {uuid.UUID(d) for d in action.document_ids}
    )
    noms_par_utilisateur = await _resoudre_noms(
        session, {action.faite_par} if action.faite_par is not None else set()
    )
    return _construire_action_vue(
        action,
        semaine_debut=synthese.semaine_debut,
        bons_par_document=bons_par_document,
        noms_par_utilisateur=noms_par_utilisateur,
    )
