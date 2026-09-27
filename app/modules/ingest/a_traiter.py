"""Écran « À traiter » de l'admin (L3-D18, L3-T8b) : documents « à
vérifier » (BL, enlèvements et factures), alias chantier en attente de
validation et articles dont le ratio proposé attend une validation.

Sous-module de `ingest`, orchestrateur de lecture seule : chaque section
(`documents`, `alias`, `articles`) est construite par sa propre fonction
privée, assemblées par `lister_a_traiter`. La sélection des documents/blocs
candidats à la propagation d'un alias (`nb_documents`/`exemple_brut` ici,
propagation dans `ingest.referentiels.valider_alias`) vit dans `referentiels
.candidats_alias` — décision du contrôleur : ne jamais dupliquer cette
sélection entre les deux endroits. `_lister_alias_en_attente` appelle les
deux briques dont `candidats_alias` est faite (`referentiels
.candidats_bruts_fournisseur`/`filtrer_candidats_par_libelle`) plutôt que
`candidats_alias` elle-même, pour charger les candidats bruts une seule
fois par `fournisseur_id` distinct même avec plusieurs alias en attente du
même fournisseur (tâche T5, décision du contrôleur : jamais une requête par
alias).

`compter_problemes_a_regler` (revue finale de la refonte du front, constats
LIENS-2, ECRAN-6, TELEPHONE-2, COUVERTURE-2) : **la** définition du nombre
de problèmes « à régler », tous mois confondus -- exactement les éléments
de la liste de l'écran « À régler » : anomalies ouvertes, documents « à
vérifier », chantiers à rattacher (alias en attente), articles à valider et,
depuis l'avenant du 27/09/2026, chantiers créés automatiquement encore à
compléter (`chantiers_a_completer`, spec §2.6). La pastille de navigation,
la tuile de la vue d'ensemble (« … en tout ») et l'en-tête de l'écran « À
régler » affichent ce même nombre ; avant ce correctif, trois compteurs de
périmètres différents (urgents de tous les mois, problèmes du mois, liste
complète) se contredisaient sur le même écran.

`CompteProblemes.controle_prix_actif` (décision d'Ilane du 24/09/2026,
`docs/dette.md`) : reflet de `ingest.commun.controle_prix_actif()`, exposé
ici -- un seul endroit -- car `GET /api/a-regler/compte` est déjà rechargé
par toutes les pages (barre de navigation, vue d'ensemble, écran « À
régler », `CLE_COMPTE_A_REGLER` côté front) : aucun autre point d'API n'a
besoin de porter ce même drapeau. Aucun calcul métier n'en découle ici, le
front ne fait qu'adapter des libellés (« Écart prix ou quantité » ->
« Écart de quantité », filtre « Prix » masqué) à partir de ce booléen.

`controle_livre_non_facture_actif` n'est plus exposé ici : depuis que
`ingest.parametres._cle_masquee` masque `delai_ligne_bl_non_facturee_j`
côté serveur (`GET /api/parametres` ne le renvoie plus tant que R06 est
désactivée, `PUT` le refuse comme une clé inconnue), aucun écran n'a plus
besoin de connaître ce second drapeau pour afficher un seuil « sans effet »
-- Réglages ne liste tout simplement plus la ligne. Le drapeau reste lu par
`ingest.commun.regles_desactivees` (donc par `ingest.suivi`, `ingest
.rapprochement` et `ingest.anomalies`) et par `ingest.parametres
._cle_masquee`, jamais par ce module."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.ingest.anomalies import compter_anomalies_ouvertes
from app.modules.ingest.commun import controle_prix_actif
from app.modules.ingest.lecture import _CONFIRMATION_PAR_ACTION, MotifLu, motifs_lus
from app.modules.ingest.models import (
    Article,
    BlocFacture,
    Chantier,
    ChantierAlias,
    Document,
    Fournisseur,
    Journal,
    Utilisateur,
)
from app.modules.ingest.referentiels import (
    candidats_bruts_fournisseur,
    filtrer_candidats_par_libelle,
)


@dataclass(frozen=True)
class DocumentATraiter:
    """Une ligne « document à vérifier » de l'écran (L3-T8b)."""

    id: uuid.UUID
    numero_interne: int
    type: str
    numero: str | None
    fournisseur: str | None
    chantier_brut: str | None
    deposant: str | None
    cree_le: datetime
    confirmation: str | None
    motifs: list[MotifLu]


@dataclass(frozen=True)
class AliasEnAttente:
    """Un alias chantier sans `chantier_id` (« demande de validation »,
    L3-D7), avec un exemple de libellé brut et le nombre de documents/blocs
    qu'il concerne encore."""

    id: uuid.UUID
    fournisseur: str
    libelle: str
    exemple_brut: str | None
    nb_documents: int
    cree_le: datetime


@dataclass(frozen=True)
class ArticleAValider:
    """Un article non validé dont le ratio proposé diffère de 1 (L3-D9)."""

    id: uuid.UUID
    fournisseur: str
    code: str
    libelle: str | None
    unite_cdt: str | None
    unite_fact: str | None
    ratio: Decimal | None
    cree_le: datetime


@dataclass(frozen=True)
class ChantierACompleter:
    """Un chantier créé automatiquement (avenant du 27/09/2026, `ingest
    .rattachement_chantier._creer_chantier_auto`, `Chantier.a_completer`),
    encore sans agence ni client -- section « Nouveaux chantiers à
    compléter » de l'écran « À régler » (spec §2.6). `nb_bons` compte les
    BL/enlèvements rattachés à ce chantier, quel que soit leur statut."""

    id: uuid.UUID
    nom: str
    nb_bons: int
    cree_le: datetime


@dataclass(frozen=True)
class ATraiter:
    """Contenu complet de l'écran « À traiter » (L3-D18)."""

    documents: list[DocumentATraiter]
    alias: list[AliasEnAttente]
    articles: list[ArticleAValider]
    chantiers_a_completer: list[ChantierACompleter]


# --------------------------------------------------------------------------
# Documents « à vérifier »
# --------------------------------------------------------------------------


async def _lister_documents_a_traiter(session: AsyncSession) -> list[DocumentATraiter]:
    """Tous les documents `a_verifier` (BL, enlèvements, factures), du plus
    ancien au plus récent (décision du contrôleur : l'admin traite d'abord ce
    qui attend depuis le plus longtemps).

    Même construction que `ingest.lecture.lister_documents` (jointures
    fournisseur/déposant, confirmation dérivée du **journal** via
    `_CONFIRMATION_PAR_ACTION`, réutilisée telle quelle plutôt que
    redéfinie) : une seule requête, quel que soit le nombre de documents à
    traiter — jamais de N+1 (décision du contrôleur)."""
    deposant_alias = aliased(Utilisateur)

    dernier_journal_confirmation = (
        select(Journal.cible_id, Journal.action)
        .where(
            Journal.cible_table == "document",
            Journal.action.in_(tuple(_CONFIRMATION_PAR_ACTION)),
        )
        .distinct(Journal.cible_id)
        .order_by(Journal.cible_id, Journal.horodatage.desc())
        .subquery()
    )

    resultat = await session.execute(
        select(
            Document,
            func.coalesce(deposant_alias.nom, deposant_alias.email),
            dernier_journal_confirmation.c.action,
            Fournisseur.nom,
        )
        .outerjoin(deposant_alias, deposant_alias.id == Document.deposant_id)
        .outerjoin(
            dernier_journal_confirmation,
            dernier_journal_confirmation.c.cible_id == cast(Document.id, String),
        )
        .outerjoin(Fournisseur, Fournisseur.id == Document.fournisseur_id)
        .where(Document.statut == "a_verifier")
        .order_by(Document.created_at.asc())
    )
    return [
        DocumentATraiter(
            id=document.id,
            numero_interne=document.numero_interne,
            type=document.type,
            numero=document.numero,
            fournisseur=nom_fournisseur,
            chantier_brut=document.chantier_brut,
            deposant=nom_deposant,
            cree_le=document.created_at,
            confirmation=(
                _CONFIRMATION_PAR_ACTION.get(action_journal)
                if action_journal is not None
                else None
            ),
            motifs=motifs_lus(document.motifs),
        )
        for (
            document,
            nom_deposant,
            action_journal,
            nom_fournisseur,
        ) in resultat.all()
    ]


# --------------------------------------------------------------------------
# Alias chantier en attente de validation
# --------------------------------------------------------------------------


async def _lister_alias_en_attente(session: AsyncSession) -> list[AliasEnAttente]:
    """Alias `chantier_id IS NULL`, avec le nombre de documents/blocs
    concernés et un exemple de libellé brut (le plus récent) — même
    sélection que la propagation de `referentiels.valider_alias`
    (`referentiels.candidats_alias`, décision du contrôleur : ne jamais
    dupliquer cette logique).

    Les candidats bruts (`referentiels.candidats_bruts_fournisseur`, deux
    requêtes) sont chargés une seule fois par `fournisseur_id` distinct,
    dans un cache local à l'appel, puis filtrés par libellé en Python
    (`referentiels.filtrer_candidats_par_libelle`, sans requête
    supplémentaire) pour chaque alias -- jamais une requête par alias
    (tâche T5 : plusieurs alias en attente d'un même fournisseur ne
    doivent jamais multiplier les requêtes)."""
    lignes = (
        await session.execute(
            select(ChantierAlias, Fournisseur.nom)
            .join(Fournisseur, Fournisseur.id == ChantierAlias.fournisseur_id)
            .where(ChantierAlias.chantier_id.is_(None))
            .order_by(ChantierAlias.created_at.asc())
        )
    ).all()

    candidats_bruts_par_fournisseur: dict[
        uuid.UUID, tuple[Sequence[Document], Sequence[BlocFacture]]
    ] = {}

    resultat: list[AliasEnAttente] = []
    for alias, nom_fournisseur in lignes:
        if alias.fournisseur_id not in candidats_bruts_par_fournisseur:
            candidats_bruts_par_fournisseur[
                alias.fournisseur_id
            ] = await candidats_bruts_fournisseur(session, alias.fournisseur_id)
        documents_bruts, blocs_bruts = candidats_bruts_par_fournisseur[
            alias.fournisseur_id
        ]
        documents, blocs = filtrer_candidats_par_libelle(
            documents_bruts, blocs_bruts, alias.libelle_brut
        )
        brut_par_date = [
            (document.chantier_brut, document.created_at) for document in documents
        ] + [(bloc.chantier_brut, bloc.created_at) for bloc in blocs]
        exemple_brut = (
            max(brut_par_date, key=lambda paire: paire[1])[0] if brut_par_date else None
        )
        resultat.append(
            AliasEnAttente(
                id=alias.id,
                fournisseur=nom_fournisseur,
                libelle=alias.libelle_brut,
                exemple_brut=exemple_brut,
                nb_documents=len(brut_par_date),
                cree_le=alias.created_at,
            )
        )
    return resultat


# --------------------------------------------------------------------------
# Articles à valider
# --------------------------------------------------------------------------


async def _lister_articles_a_valider(session: AsyncSession) -> list[ArticleAValider]:
    """Articles non validés dont le ratio proposé diffère de 1 (L3-D9,
    décision du contrôleur : « à valider » = non validé avec un ratio
    proposé ≠ 1)."""
    resultat = await session.execute(
        select(Article, Fournisseur.nom)
        .join(Fournisseur, Fournisseur.id == Article.fournisseur_id)
        .where(
            Article.valide.is_(False),
            Article.ratio.is_not(None),
            Article.ratio != 1,
        )
        .order_by(Article.created_at.asc())
    )
    return [
        ArticleAValider(
            id=article.id,
            fournisseur=nom_fournisseur,
            code=article.code,
            libelle=article.libelle,
            unite_cdt=article.unite_cdt,
            unite_fact=article.unite_fact,
            ratio=article.ratio,
            cree_le=article.created_at,
        )
        for article, nom_fournisseur in resultat.all()
    ]


# --------------------------------------------------------------------------
# Chantiers à compléter (avenant du 27/09/2026, spec §2.6)
# --------------------------------------------------------------------------


async def _lister_chantiers_a_completer(
    session: AsyncSession,
) -> list[ChantierACompleter]:
    """Chantiers `a_completer` (créés automatiquement, jamais encore
    complétés ni fusionnés -- un chantier fusionné repasse `a_completer` à
    faux, spec §2.7), du plus ancien au plus récent. `nb_bons` (BL/
    enlèvements rattachés, jointure externe groupée) en une seule requête,
    jamais une par chantier (même décision que le reste de ce fichier) --
    un bon archivé ne compte pas (fix round 1, même exclusion que partout
    ailleurs où un compte porte sur des documents, `ingest.bilan` et
    `corrections.archiver_document`)."""
    resultat = await session.execute(
        select(
            Chantier.id,
            Chantier.nom_canonique,
            Chantier.created_at,
            func.count(Document.id),
        )
        .outerjoin(
            Document,
            (Document.chantier_id == Chantier.id)
            & (Document.type.in_(("bl", "enlevement")))
            & (Document.statut != "archive"),
        )
        .where(Chantier.a_completer.is_(True))
        .group_by(Chantier.id)
        .order_by(Chantier.created_at.asc())
    )
    return [
        ChantierACompleter(id=chantier_id, nom=nom, nb_bons=nb_bons, cree_le=cree_le)
        for chantier_id, nom, cree_le, nb_bons in resultat.all()
    ]


# --------------------------------------------------------------------------
# lister_a_traiter
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CompteProblemes:
    """Nombre de problèmes « à régler », tous mois confondus (voir le
    docstring de module) : `nb_problemes` compte chaque élément de la liste
    de l'écran « À régler » une fois ; `nb_urgents` les anomalies ouvertes de
    gravité haute (seuls problèmes « Urgent » de cette liste)."""

    nb_problemes: int
    nb_urgents: int
    controle_prix_actif: bool


async def compter_problemes_a_regler(session: AsyncSession) -> CompteProblemes:
    """Voir le docstring de module : anomalies ouvertes (même périmètre que
    `lister_anomalies(statut="ouverte")`, sans plafond) plus les trois
    sections de `lister_a_traiter`, jamais une seconde sélection."""
    nb_anomalies, nb_urgents = await compter_anomalies_ouvertes(session)
    a_traiter = await lister_a_traiter(session)
    return CompteProblemes(
        nb_problemes=nb_anomalies
        + len(a_traiter.documents)
        + len(a_traiter.alias)
        + len(a_traiter.articles)
        + len(a_traiter.chantiers_a_completer),
        nb_urgents=nb_urgents,
        controle_prix_actif=controle_prix_actif(),
    )


async def lister_a_traiter(session: AsyncSession) -> ATraiter:
    """Contenu complet de l'écran « À traiter » (L3-D18) : documents « à
    vérifier », alias chantier en attente, articles à valider, chantiers
    créés automatiquement encore à compléter (avenant du 27/09/2026)."""
    return ATraiter(
        documents=await _lister_documents_a_traiter(session),
        alias=await _lister_alias_en_attente(session),
        articles=await _lister_articles_a_valider(session),
        chantiers_a_completer=await _lister_chantiers_a_completer(session),
    )
