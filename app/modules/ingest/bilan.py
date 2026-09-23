"""Bilan par chantier (`ingest/bilan.py`, L5-T1) : premier des agrégats de
restitution du lot 5 — fondation réutilisée par les cinq tâches suivantes
(vue par fournisseur, par BL, vue inverse, export CSV).

Décision L5-D1 : les agrégats vivent dans `ingest`, en dataclasses ; aucune
somme n'est faite dans un routeur (L5-T3, pas cette tâche) ni dans le front.
Décision L5-D2 : pas de table d'agrégat ni de cache, tout est recalculé à la
demande par des requêtes SQL agrégées (`func.sum`/`func.count`), le volume
d'un seul client restant faible.

Le point délicat de cette tâche (décision du contrôleur, L5-D3) : les
quatre montants (`facture_ht`, `rapproche`, `en_ecart`, `non_justifie`) ne
forment **pas** une partition du facturé HT. Ce sont quatre projections
indépendantes sur le même ensemble de blocs :
- `facture_ht` : tous les blocs du périmètre ;
- `rapproche` : ceux dont `statut_rapprochement = 'recu'` ;
- `en_ecart` : ceux portant au moins une anomalie **ouverte** de quantité ou
  de prix (voir `REGLES_QUANTITE_OU_PRIX` ci-dessous) ;
- `non_justifie` : ceux dont `statut_rapprochement` vaut `'non_recu'` ou
  `'pas_de_bon'`.
Un bloc `recu` qui porte une anomalie ouverte compte donc à la fois dans
`rapproche` et dans `en_ecart` (test
`test_bilan_bloc_recu_avec_anomalie_ouverte_compte_dans_rapproche_et_en_ecart`).

Le chantier d'un bloc (constat 2 du plan, décision du contrôleur) :
`COALESCE(bloc_facture.chantier_id, document.chantier_id)` où `document`
est la **facture** porteuse du bloc (`bloc_facture.facture_id`) — un BL
porte son propre chantier sur le document, un bloc de facture le porte sur
lui-même. Distinct de `ingest.anomalies.CHANTIER_ID_RESOLU` (qui résout le
chantier *d'une anomalie*, avec `Anomalie.chantier_id` en tête pour les
anomalies de suivi comme R16) : ici on résout le chantier *d'un bloc*, pas
d'une anomalie, donc une expression différente, décidée explicitement par
le contrôleur plutôt que réutilisée. Les blocs sans chantier résolu ne
disparaissent pas : ils sont groupés sous une ligne `chantier_id=None`
(décision du contrôleur — un montant qui s'évapore serait pire qu'un
montant mal rangé).

Le mois d'un bloc (L5-D4) est celui de sa facture : `document.date_doc`,
sinon `document.created_at` converti en Europe/Paris
(`app.core.fuseau.FUSEAU_PARIS`) — jamais `date_bl`.

`REGLES_QUANTITE_OU_PRIX` (R03 à R09) est définie une seule fois ici, nommée
(décision du contrôleur), et sert à déterminer `en_ecart`.

Ruling L5-R3 (tour de correction 1, `ingest/rapprochement.py`) : R07, R08,
R09, R13 et R17 ne posaient que `ligne_id` sur l'anomalie qu'elles
produisent, jamais `bloc_id` (la règle pure ne reçoit que la ligne). Ce
module contournait le trou par un `COALESCE(anomalie.bloc_id,
ligne.bloc_id)` — retiré depuis que `rapprocher_facture` complète lui-même
`bloc_id` à partir de la ligne (même idiome que son complément de
`document_id`, Ruling R17 du lot 4) : une seule source de vérité, portée par
l'orchestrateur qui sait ce que le module pur ignore, jamais recopiée dans
chaque lecture.

Ruling L5-R4 (tour de correction 1) : `MontantsBilan.nb_anomalies_ouvertes`
compte désormais **toutes** les anomalies ouvertes rattachées à un bloc du
périmètre, quelle que soit leur règle (CDC §4.6, « nombre d'anomalies
ouvertes », sans restriction) — voir le docstring de `MontantsBilan` pour la
distinction avec `en_ecart`, qui garde son périmètre restreint. Le Ruling
L5-R3 ci-dessus rend cette extension sûre : toute anomalie de facture
rattachée à une ligne porte désormais un `bloc_id`, donc son chantier se
résout.

Tour de correction 1, deuxième point : l'agrégation et le tri sont
désormais entièrement portés par la requête SQL (deux sous-requêtes
imbriquées, jamais un JOIN direct entre `ligne` et `anomalie` sur le même
bloc, qui multiplierait les lignes de chacun par l'autre et fausserait les
sommes) plutôt que combinés et triés en Python : `ORDER BY` avec
`chantier_id` comme dernière clé de tri, pour que deux chantiers de même
nom et de même montant facturé ne puissent plus s'échanger d'un appel à
l'autre.

L5-T2 : niveaux fournisseur et BL, plus la vue inverse. Décision du
contrôleur (le vrai enjeu de la tâche) : ne jamais réécrire les quatre
montants une deuxième fois. `_sous_requete_blocs`/`_sous_requete_anomalies`
(les deux sous-requêtes ci-dessus, désormais partagées) et
`_expressions_montants` (les quatre `CASE WHEN`/le compte, ci-dessus)
portent le calcul une seule fois pour les cinq fonctions du module ; seule
la clé de regroupement change (`Chantier`, `Fournisseur`, ou l'identité du
bloc lui-même pour le niveau BL) : `_bilan_par_chantier_interne` est
partagée par `bilan_par_chantier` et sa vue inverse
`bilan_chantiers_du_fournisseur`, `_bilan_par_fournisseur_interne` par
`bilan_par_fournisseur` et sa vue inverse `bilan_par_fournisseur_global` —
un filtre de périmètre supplémentaire (`filtre_perimetre`, une fonction de
la sous-requête `blocs` vers une condition SQL) est la seule différence
entre une fonction et sa vue inverse, exactement ce que demandait la
décision du contrôleur (« si [la vue inverse] a besoin d'une requête
différente, c'est que la factorisation n'est pas la bonne »).

Le fournisseur d'un bloc n'est jamais recalculé comme le chantier : une
facture porte son fournisseur (`Document.fournisseur_id`), un bloc n'en a
pas de propre (pas de `chantier_brut`/`chantier_id` équivalent), donc pas
de `COALESCE` ici -- juste `Document.fournisseur_id`, nul quand la facture
n'a pas de fournisseur résolu. Même règle que pour le chantier (décision du
contrôleur) : un bloc sans fournisseur résolu ne disparaît pas, il rejoint
une ligne `fournisseur_id=None`.

Le niveau BL (décision du contrôleur) est le bloc de facture, pas le
document BL : c'est le bloc qui porte le montant facturé et le statut de
rapprochement. `bl_document_id`/`facture_id` sont renvoyés tels quels
(`bl_document_id` reste `None` tant que la photo du BL n'a pas été
retrouvée par le rapprochement, L4-D4).

Export détaillé (décision d'Ilane du 23/09/2026, réponse à Q3 du lot 5) :
`bilan_detail` -- une ligne par ligne de facture (`ligne`), sur tout le
périmètre `mois`/`agence`, en plus des cinq agrégats ci-dessus. Réutilise
`_sous_requete_blocs`/`_conditions_base`/`_condition_agence` (même
résolution du chantier, même chantier non résolu conservé). Voir le
docstring de `bilan_detail` pour le piège évité (jamais un JOIN direct
`ligne`/`anomalie`, qui multiplierait les lignes renvoyées) et la limite
documentée sur R06 (`docs/dette.md`)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.anomalies import CHANTIER_ID_RESOLU
from app.modules.ingest.models import (
    Anomalie,
    BlocFacture,
    Chantier,
    Document,
    Fournisseur,
    Ligne,
    RapprochementLigne,
)

# Règles de quantité et de prix (CDC §5) : les seules dont une anomalie
# ouverte fait entrer un bloc dans « en écart » (décision du contrôleur,
# L5-T1). R01/R02 (absence de BL/mention "pas de bon") et R10-R13/R17
# (contrôles de document, doublons, avoirs) n'y figurent pas : ce ne sont
# pas des écarts de quantité ou de prix sur une ligne.
REGLES_QUANTITE_OU_PRIX: frozenset[str] = frozenset(
    {"R03", "R04", "R05", "R06", "R07", "R08", "R09"}
)

# Types de ligne qui composent un montant facturé (CDC §5/§6) : une ligne
# "commentaire" ne porte jamais de montant.
_TYPES_LIGNE_FACTUREE: tuple[str, ...] = ("article", "eco")

_STATUTS_NON_JUSTIFIE: tuple[str, ...] = ("non_recu", "pas_de_bon")


@dataclass(frozen=True)
class MontantsBilan:
    """Les quatre montants d'un périmètre (L5-D3) plus le nombre
    d'anomalies ouvertes qui s'y rattachent — tous des `Decimal` sauf le
    compte (jamais de `float`, CLAUDE.md).

    `en_ecart` et `nb_anomalies_ouvertes` répondent à deux questions
    différentes (Ruling L5-R4, tour de correction 1) : `en_ecart` est un
    **montant**, restreint aux anomalies de quantité ou de prix
    (`REGLES_QUANTITE_OU_PRIX`) parce que ce sont les seules à remettre en
    cause une somme facturée ; `nb_anomalies_ouvertes` est un **compte**,
    qui porte sur toutes les anomalies ouvertes rattachées à un bloc du
    périmètre, quelle que soit leur règle (CDC §4.6 : « nombre d'anomalies
    ouvertes », sans restriction). Un chantier dont un bloc n'a jamais reçu
    de BL (R01, gravité haute) affiche donc `nb_anomalies_ouvertes > 0`
    alors que `en_ecart` peut rester à `0` : ce n'est pas un écart de
    quantité ou de prix, mais ce n'en est pas moins une anomalie ouverte à
    traiter. Une anomalie sans bloc n'entre jamais dans `en_ecart`; elle
    entre dans le compte des niveaux auxquels son document ou son chantier
    explicite permet de l'attribuer."""

    facture_ht: Decimal
    rapproche: Decimal
    en_ecart: Decimal
    non_justifie: Decimal
    nb_anomalies_ouvertes: int


@dataclass(frozen=True)
class LigneBilanChantier:
    """Une ligne du bilan au niveau chantier. `chantier_id=None` regroupe
    les blocs dont le chantier n'a pas pu être résolu (décision du
    contrôleur) : `nom_canonique`/`agence`/`client` valent alors `None`,
    c'est au front de nommer cette ligne (L5-T4/T5, hors de cette tâche).
    `client` : ajout hors CDC demandé le 23/09/2026 (`docs/dette.md`)."""

    chantier_id: uuid.UUID | None
    nom_canonique: str | None
    agence: str | None
    client: str | None
    montants: MontantsBilan


@dataclass(frozen=True)
class LigneBilanFournisseur:
    """Une ligne du bilan au niveau fournisseur (L5-T2), dans un chantier
    donné ou au niveau global de la vue inverse. `fournisseur_id=None`
    regroupe les blocs dont le fournisseur n'a pas pu être résolu (la
    facture porteuse n'a pas de `fournisseur_id`, décision du contrôleur —
    même principe que `LigneBilanChantier.chantier_id=None`) : `nom` vaut
    alors `None`, c'est au front de nommer cette ligne."""

    fournisseur_id: uuid.UUID | None
    nom: str | None
    montants: MontantsBilan


@dataclass(frozen=True)
class LigneBilanBl:
    """Une ligne du bilan au niveau BL (L5-T2) : un bloc de facture
    (« Concerne le B.L. n°... »), pas le document BL lui-même — décision du
    contrôleur, c'est le bloc qui porte le montant facturé et le statut de
    rapprochement. `bl_document_id` est renseigné quand la photo du BL a
    été retrouvée par le rapprochement (L4-D4), `None` sinon : c'est ce qui
    permet au front d'ouvrir le document source. `facture_id` identifie la
    facture porteuse du bloc."""

    bloc_id: uuid.UUID
    numero_bl: str | None
    date_bl: date | None
    statut_rapprochement: str | None
    bl_document_id: uuid.UUID | None
    facture_id: uuid.UUID
    montants: MontantsBilan


def _premier_jour_mois_suivant(premier_jour: date) -> date:
    """Premier jour du mois calendaire suivant `premier_jour` (qui doit
    déjà être un 1er du mois) — calcul en stdlib pur, comme
    `rapprochement._six_mois_avant`."""
    if premier_jour.month == 12:
        return date(premier_jour.year + 1, 1, 1)
    return date(premier_jour.year, premier_jour.month + 1, 1)


def _condition_mois(mois: date, document: Any = Document) -> Any:
    """Condition SQL du filtre `mois` (L5-D4) : le mois d'un bloc est celui
    de sa facture, lue sur `document.date_doc` (comparaison de dates civiles,
    aucune conversion de fuseau nécessaire) ; à défaut, celui de
    `document.created_at` converti en Europe/Paris (comparaison d'instants,
    même mécanique que `api.anomalies._debut_jour_paris`/`_fin_jour_paris`).
    Seuls le mois et l'année de `mois` comptent (le jour est ignoré, au cas
    où l'appelant ne transmettrait pas strictement un 1er du mois).

    Cas limite couvert par
    `test_bilan_filtre_mois_facture_creee_le_1er_a_paris_avant_minuit_utc`
    (tour de correction 1) : une facture sans `date_doc`, créée le 1er du
    mois à 00h30 heure de Paris, est encore la veille en UTC (heure d'été,
    UTC+2) — `debut_instant`/`fin_instant` sont construits directement avec
    `tzinfo=FUSEAU_PARIS`, jamais convertis depuis un instant UTC naïf, pour
    que la comparaison porte sur le bon jour civil parisien quel que soit le
    fuseau de la session Postgres."""
    premier_jour = date(mois.year, mois.month, 1)
    jour_suivant = _premier_jour_mois_suivant(premier_jour)
    debut_instant = datetime(
        premier_jour.year, premier_jour.month, 1, tzinfo=FUSEAU_PARIS
    )
    fin_instant = datetime(
        jour_suivant.year, jour_suivant.month, 1, tzinfo=FUSEAU_PARIS
    )
    return or_(
        and_(
            document.date_doc.is_not(None),
            document.date_doc >= premier_jour,
            document.date_doc < jour_suivant,
        ),
        and_(
            document.date_doc.is_(None),
            document.created_at >= debut_instant,
            document.created_at < fin_instant,
        ),
    )


@dataclass(frozen=True)
class _ExpressionsMontants:
    """Les quatre montants (L5-D3) et le compte d'anomalies ouvertes
    (Ruling L5-R4), sous forme d'expressions SQL agrégées -- calculées une
    seule fois par `_expressions_montants` et réutilisées par les cinq
    fonctions publiques du module. Champs typés `Any` : ce sont des
    expressions SQLAlchemy (`func.sum(...)`/`case(...)`), pas des valeurs,
    comme les autres expressions de ce module (`_condition_mois`)."""

    facture_ht: Any
    rapproche: Any
    en_ecart: Any
    non_justifie: Any
    nb_anomalies_ouvertes: Any


def _conditions_base(mois: date | None) -> list[Any]:
    """Conditions communes aux cinq niveaux du bilan : type facture, non
    archivée (même formulation que le lot 4), plus le filtre mois (L5-D4)
    si fourni."""
    conditions: list[Any] = [
        Document.type == "facture",
        Document.statut != "archive",
    ]
    if mois is not None:
        conditions.append(_condition_mois(mois))
    return conditions


def _sous_requete_blocs(conditions: list[Any]) -> Any:
    """Sous-requête commune aux cinq niveaux du bilan (L5-T1, étendue en
    L5-T2) : une ligne par bloc du périmètre (`conditions`), avec le
    chantier résolu (`COALESCE(bloc_facture.chantier_id,
    document.chantier_id)`, constat 2 du plan), le fournisseur résolu
    (`Document.fournisseur_id` -- une facture porte son fournisseur, un
    bloc n'a pas de `chantier_brut`/`chantier_id` équivalent pour le
    fournisseur, donc pas de `COALESCE` ici), le statut de rapprochement,
    le montant HT (somme des lignes "article"/"eco" du bloc, `0` si
    aucune), plus les champs propres au niveau BL (`numero_bl`, `date_bl`,
    `bl_document_id`, `facture_id`) : ces colonnes supplémentaires ne
    coûtent rien aux niveaux chantier et fournisseur, qui ne les
    sélectionnent simplement pas dans la requête englobante."""
    return (
        select(
            BlocFacture.id.label("bloc_id"),
            func.coalesce(BlocFacture.chantier_id, Document.chantier_id).label(
                "chantier_id"
            ),
            Document.fournisseur_id.label("fournisseur_id"),
            BlocFacture.statut_rapprochement.label("statut_rapprochement"),
            BlocFacture.numero_bl.label("numero_bl"),
            BlocFacture.date_bl.label("date_bl"),
            BlocFacture.bl_document_id.label("bl_document_id"),
            BlocFacture.facture_id.label("facture_id"),
            func.coalesce(func.sum(Ligne.montant_ht), Decimal("0")).label("montant_ht"),
        )
        .select_from(BlocFacture)
        .join(Document, Document.id == BlocFacture.facture_id)
        .outerjoin(
            Ligne,
            and_(
                Ligne.bloc_id == BlocFacture.id,
                Ligne.type_ligne.in_(_TYPES_LIGNE_FACTUREE),
            ),
        )
        .where(*conditions)
        .group_by(
            BlocFacture.id,
            BlocFacture.chantier_id,
            Document.chantier_id,
            Document.fournisseur_id,
            BlocFacture.statut_rapprochement,
            BlocFacture.numero_bl,
            BlocFacture.date_bl,
            BlocFacture.bl_document_id,
            BlocFacture.facture_id,
        )
        .subquery()
    )


def _sous_requete_anomalies(mois: date | None) -> Any:
    """Une ligne par anomalie ouverte avec ses origines attribuables.

    Le chantier réutilise strictement `CHANTIER_ID_RESOLU`, comme l'écran
    Anomalies. Le fournisseur vient en priorité du document de l'anomalie,
    puis de la facture portée par son bloc ; le BL vient de son `bloc_id`.
    Une anomalie R16 est donc attribuable au chantier mais ni au fournisseur
    ni au BL ; une R11/R15 de document peut l'être au chantier et au
    fournisseur sans l'être à un BL. Les anomalies de bloc suivent le mois
    et le statut de leur facture (L5-D4), celles de document suivent le mois
    et le statut de ce document. Pour une anomalie sans bloc ni document,
    le mois porte sur `Anomalie.created_at`, comme le filtre de période de
    l'écran Anomalies. Chaque branche est exclusive, donc une anomalie ne
    peut entrer qu'une fois dans la sous-requête.
    """
    facture_bloc = aliased(Document)
    conditions: list[Any] = [
        Anomalie.statut == "ouverte",
        or_(
            and_(
                Anomalie.bloc_id.is_not(None),
                facture_bloc.type == "facture",
                facture_bloc.statut != "archive",
            ),
            and_(
                Anomalie.bloc_id.is_(None),
                Anomalie.document_id.is_not(None),
                Document.statut != "archive",
            ),
            and_(
                Anomalie.bloc_id.is_(None),
                Anomalie.document_id.is_(None),
            ),
        ),
    ]
    if mois is not None:
        premier_jour = date(mois.year, mois.month, 1)
        jour_suivant = _premier_jour_mois_suivant(premier_jour)
        debut_instant = datetime(
            premier_jour.year, premier_jour.month, 1, tzinfo=FUSEAU_PARIS
        )
        fin_instant = datetime(
            jour_suivant.year, jour_suivant.month, 1, tzinfo=FUSEAU_PARIS
        )
        conditions.append(
            or_(
                and_(
                    Anomalie.bloc_id.is_not(None),
                    _condition_mois(mois, facture_bloc),
                ),
                and_(
                    Anomalie.bloc_id.is_(None),
                    Anomalie.document_id.is_not(None),
                    _condition_mois(mois),
                ),
                and_(
                    Anomalie.bloc_id.is_(None),
                    Anomalie.document_id.is_(None),
                    Anomalie.created_at >= debut_instant,
                    Anomalie.created_at < fin_instant,
                ),
            )
        )
    return (
        select(
            Anomalie.id.label("anomalie_id"),
            Anomalie.bloc_id.label("bloc_id"),
            Anomalie.document_id.label("document_id"),
            CHANTIER_ID_RESOLU.label("chantier_id"),
            func.coalesce(Document.fournisseur_id, facture_bloc.fournisseur_id).label(
                "fournisseur_id"
            ),
            Anomalie.regle.label("regle"),
        )
        .select_from(Anomalie)
        .outerjoin(Document, Document.id == Anomalie.document_id)
        .outerjoin(BlocFacture, BlocFacture.id == Anomalie.bloc_id)
        .outerjoin(facture_bloc, facture_bloc.id == BlocFacture.facture_id)
        .where(*conditions)
        .subquery()
    )


def _comptes_anomalies(
    anomalies: Any, *groupes: Any, filtre_perimetre: Any | None = None
) -> Any:
    """Compte les anomalies une fois selon les origines d'un niveau."""
    requete = (
        select(*groupes, func.count(anomalies.c.anomalie_id).label("nb_total"))
        .select_from(anomalies)
        .group_by(*groupes)
    )
    if filtre_perimetre is not None:
        requete = requete.where(filtre_perimetre)
    return requete.subquery()


def _anomalies_qte_prix_par_bloc(anomalies: Any) -> Any:
    """Sous-ensemble par bloc utilisé exclusivement par `en_ecart`."""
    return (
        select(
            anomalies.c.bloc_id,
            func.count()
            .filter(anomalies.c.regle.in_(tuple(REGLES_QUANTITE_OU_PRIX)))
            .label("nb_qte_prix"),
        )
        .where(anomalies.c.bloc_id.is_not(None))
        .group_by(anomalies.c.bloc_id)
        .subquery()
    )


def _expressions_montants(
    blocs: Any, anomalies_qte_prix: Any, nb_anomalies_ouvertes: Any
) -> _ExpressionsMontants:
    """Les quatre montants et le compte d'anomalies (L5-D3/Ruling L5-R4),
    à partir des deux sous-requêtes ci-dessus -- le point que la revue de
    L5-T1 réclamait de ne jamais recopier. `blocs` et `anomalies` doivent
    déjà être joints par la requête appelante
    (`outerjoin(anomalies, anomalies.c.bloc_id == blocs.c.bloc_id)`), sans
    quoi `anomalies.c.*` n'est pas résoluble par le moteur SQL. Ces
    expressions sont des agrégats (`func.sum`/`func.count`) : la requête
    englobante peut les grouper par n'importe quelle clé (chantier,
    fournisseur, ou l'identité du bloc lui-même pour le niveau BL, où
    chaque groupe ne contient jamais plus d'une ligne `blocs`) sans changer
    un seul `CASE WHEN`."""
    return _ExpressionsMontants(
        facture_ht=func.sum(blocs.c.montant_ht),
        rapproche=func.sum(
            case((blocs.c.statut_rapprochement == "recu", blocs.c.montant_ht), else_=0)
        ),
        en_ecart=func.sum(
            case(
                (
                    func.coalesce(anomalies_qte_prix.c.nb_qte_prix, 0) > 0,
                    blocs.c.montant_ht,
                ),
                else_=0,
            )
        ),
        non_justifie=func.sum(
            case(
                (
                    blocs.c.statut_rapprochement.in_(_STATUTS_NON_JUSTIFIE),
                    blocs.c.montant_ht,
                ),
                else_=0,
            )
        ),
        nb_anomalies_ouvertes=func.coalesce(nb_anomalies_ouvertes, 0),
    )


def _montants_bilan(ligne: Any) -> MontantsBilan:
    """Extrait les cinq colonnes de montants d'une ligne de résultat --
    partagé par les cinq fonctions publiques, qui sélectionnent toutes ces
    colonnes sous les mêmes noms (`facture_ht`, `rapproche`, `en_ecart`,
    `non_justifie`, `nb_anomalies_ouvertes`, via `_expressions_montants`)."""
    return MontantsBilan(
        facture_ht=ligne.facture_ht,
        rapproche=ligne.rapproche,
        en_ecart=ligne.en_ecart,
        non_justifie=ligne.non_justifie,
        nb_anomalies_ouvertes=ligne.nb_anomalies_ouvertes,
    )


def _condition_agence(blocs: Any, agence: str) -> Any:
    """Filtre par agence (L5-D6) : l'agence est un attribut du chantier
    résolu du bloc, jamais du bloc lui-même. Exprimé par une sous-requête
    corrélée sur les chantiers de cette agence plutôt que par une jointure,
    pour s'appliquer identiquement que le niveau englobant groupe par
    chantier, par fournisseur ou par bloc -- le chantier n'y est alors pas
    forcément joint pour l'affichage (ex. `bilan_par_fournisseur`)."""
    return blocs.c.chantier_id.in_(select(Chantier.id).where(Chantier.agence == agence))


def _filtre_anomalies_portee(
    anomalies: Any,
    *,
    groupe: Any,
    agence: str | None,
    filtre_anomalies: Callable[[Any], Any] | None,
) -> Any | None:
    """Reprend sur les comptes d'anomalies les filtres hors mois/statut,
    déjà portés directement par `_sous_requete_anomalies`."""
    conditions: list[Any] = [
        or_(
            groupe.is_not(None),
            anomalies.c.bloc_id.is_not(None),
            anomalies.c.document_id.is_not(None),
        )
    ]
    if filtre_anomalies is not None:
        conditions.append(filtre_anomalies(anomalies))
    if agence is not None:
        conditions.append(_condition_agence(anomalies, agence))
    return and_(*conditions) if conditions else None


def _condition_exact_ou_nul(colonne: Any, valeur: uuid.UUID | None) -> Any:
    """Condition d'égalité sur une colonne résolue d'un bloc (`chantier_id`
    ou `fournisseur_id`) qui accepte `valeur=None` : sélectionne alors les
    blocs dont cette colonne n'a pas pu être résolue (décision du
    contrôleur -- le « chantier non résolu » ou le « fournisseur non
    résolu » d'un périmètre, jamais silencieusement ignorés), plutôt que de
    ne rien filtrer."""
    return colonne.is_(None) if valeur is None else colonne == valeur


async def _bilan_par_chantier_interne(
    session: AsyncSession,
    *,
    mois: date | None,
    agence: str | None,
    filtre_perimetre: Callable[[Any], Any] | None,
    filtre_anomalies: Callable[[Any], Any] | None,
) -> list[LigneBilanChantier]:
    """Construction partagée par `bilan_par_chantier` et sa vue inverse
    `bilan_chantiers_du_fournisseur` (L5-T2) : même regroupement par
    chantier, `filtre_perimetre` (une fonction de la sous-requête `blocs`
    vers une condition SQL) porte le seul filtre de périmètre propre à
    l'appelant -- aucun pour `bilan_par_chantier`, un fournisseur donné pour
    `bilan_chantiers_du_fournisseur`. Si la vue inverse avait besoin d'une
    requête différente, la factorisation serait la mauvaise (décision du
    contrôleur) : elle n'en a pas besoin.

    Triée par `facture_ht` décroissant puis par nom de chantier puis par
    `chantier_id` (tour de correction 1, L5-T1 : dernière clé de tri, pour
    que deux chantiers de même nom et de même montant ne s'échangent jamais
    d'un appel à l'autre) -- la ligne `chantier_id=None` (blocs sans
    chantier résolu) se départage en dernier à montant égal."""
    blocs = _sous_requete_blocs(_conditions_base(mois))
    anomalies = _sous_requete_anomalies(mois)
    anomalies_qte_prix = _anomalies_qte_prix_par_bloc(anomalies)
    comptes_anomalies = _comptes_anomalies(
        anomalies,
        anomalies.c.chantier_id,
        filtre_perimetre=_filtre_anomalies_portee(
            anomalies,
            groupe=anomalies.c.chantier_id,
            agence=agence,
            filtre_anomalies=filtre_anomalies,
        ),
    )
    montants = _expressions_montants(
        blocs, anomalies_qte_prix, comptes_anomalies.c.nb_total
    )

    requete = (
        select(
            Chantier.id.label("chantier_id"),
            Chantier.nom_canonique.label("nom_canonique"),
            Chantier.agence.label("agence"),
            Chantier.client.label("client"),
            montants.facture_ht.label("facture_ht"),
            montants.rapproche.label("rapproche"),
            montants.en_ecart.label("en_ecart"),
            montants.non_justifie.label("non_justifie"),
            montants.nb_anomalies_ouvertes.label("nb_anomalies_ouvertes"),
        )
        .select_from(blocs)
        .outerjoin(anomalies_qte_prix, anomalies_qte_prix.c.bloc_id == blocs.c.bloc_id)
        .outerjoin(
            comptes_anomalies,
            comptes_anomalies.c.chantier_id.is_not_distinct_from(blocs.c.chantier_id),
        )
        .outerjoin(Chantier, Chantier.id == blocs.c.chantier_id)
        .group_by(
            Chantier.id,
            Chantier.nom_canonique,
            Chantier.agence,
            Chantier.client,
            comptes_anomalies.c.nb_total,
        )
    )
    if filtre_perimetre is not None:
        requete = requete.where(filtre_perimetre(blocs))
    if agence is not None:
        requete = requete.where(_condition_agence(blocs, agence))

    requete = requete.order_by(
        montants.facture_ht.desc(), Chantier.nom_canonique.asc(), Chantier.id.asc()
    )

    lignes = (await session.execute(requete)).all()
    return [
        LigneBilanChantier(
            chantier_id=ligne.chantier_id,
            nom_canonique=ligne.nom_canonique,
            agence=ligne.agence,
            client=ligne.client,
            montants=_montants_bilan(ligne),
        )
        for ligne in lignes
    ]


async def bilan_par_chantier(
    session: AsyncSession,
    *,
    mois: date | None,
    agence: str | None,
) -> list[LigneBilanChantier]:
    """Bilan agrégé par chantier (L5-T1). Un bloc de facture archivée
    n'entre dans aucun montant (`Document.statut != "archive"`, même
    formulation que le lot 4). Voir `_bilan_par_chantier_interne` pour la
    construction (partagée avec la vue inverse, L5-T2)."""
    return await _bilan_par_chantier_interne(
        session,
        mois=mois,
        agence=agence,
        filtre_perimetre=None,
        filtre_anomalies=None,
    )


async def bilan_chantiers_du_fournisseur(
    session: AsyncSession,
    *,
    fournisseur_id: uuid.UUID | None,
    mois: date | None,
    agence: str | None,
) -> list[LigneBilanChantier]:
    """Vue inverse (L5-T2), second niveau : bilan agrégé par chantier,
    restreint aux blocs d'un fournisseur donné (`fournisseur_id=None`
    sélectionne le fournisseur non résolu, décision du contrôleur). Même
    construction que `bilan_par_chantier` (`_bilan_par_chantier_interne`),
    avec ce filtre de périmètre en plus -- point d'entrée de la navigation
    « du fournisseur vers le chantier »."""
    return await _bilan_par_chantier_interne(
        session,
        mois=mois,
        agence=agence,
        filtre_perimetre=lambda blocs: _condition_exact_ou_nul(
            blocs.c.fournisseur_id, fournisseur_id
        ),
        filtre_anomalies=lambda anomalies: _condition_exact_ou_nul(
            anomalies.c.fournisseur_id, fournisseur_id
        ),
    )


async def _bilan_par_fournisseur_interne(
    session: AsyncSession,
    *,
    mois: date | None,
    agence: str | None,
    filtre_perimetre: Callable[[Any], Any] | None,
    filtre_anomalies: Callable[[Any], Any] | None,
) -> list[LigneBilanFournisseur]:
    """Construction partagée par `bilan_par_fournisseur` et sa vue inverse
    `bilan_par_fournisseur_global` (L5-T2) : même principe que
    `_bilan_par_chantier_interne`, groupé par fournisseur plutôt que par
    chantier."""
    blocs = _sous_requete_blocs(_conditions_base(mois))
    anomalies = _sous_requete_anomalies(mois)
    anomalies_qte_prix = _anomalies_qte_prix_par_bloc(anomalies)
    comptes_anomalies = _comptes_anomalies(
        anomalies,
        anomalies.c.fournisseur_id,
        filtre_perimetre=_filtre_anomalies_portee(
            anomalies,
            groupe=anomalies.c.fournisseur_id,
            agence=agence,
            filtre_anomalies=filtre_anomalies,
        ),
    )
    montants = _expressions_montants(
        blocs, anomalies_qte_prix, comptes_anomalies.c.nb_total
    )

    requete = (
        select(
            Fournisseur.id.label("fournisseur_id"),
            Fournisseur.nom.label("nom"),
            montants.facture_ht.label("facture_ht"),
            montants.rapproche.label("rapproche"),
            montants.en_ecart.label("en_ecart"),
            montants.non_justifie.label("non_justifie"),
            montants.nb_anomalies_ouvertes.label("nb_anomalies_ouvertes"),
        )
        .select_from(blocs)
        .outerjoin(anomalies_qte_prix, anomalies_qte_prix.c.bloc_id == blocs.c.bloc_id)
        .outerjoin(
            comptes_anomalies,
            comptes_anomalies.c.fournisseur_id.is_not_distinct_from(
                blocs.c.fournisseur_id
            ),
        )
        .outerjoin(Fournisseur, Fournisseur.id == blocs.c.fournisseur_id)
        .group_by(Fournisseur.id, Fournisseur.nom, comptes_anomalies.c.nb_total)
    )
    if filtre_perimetre is not None:
        requete = requete.where(filtre_perimetre(blocs))
    if agence is not None:
        requete = requete.where(_condition_agence(blocs, agence))

    requete = requete.order_by(
        montants.facture_ht.desc(), Fournisseur.nom.asc(), Fournisseur.id.asc()
    )

    lignes = (await session.execute(requete)).all()
    return [
        LigneBilanFournisseur(
            fournisseur_id=ligne.fournisseur_id,
            nom=ligne.nom,
            montants=_montants_bilan(ligne),
        )
        for ligne in lignes
    ]


async def bilan_par_fournisseur(
    session: AsyncSession,
    *,
    chantier_id: uuid.UUID | None,
    mois: date | None,
    agence: str | None,
) -> list[LigneBilanFournisseur]:
    """Bilan agrégé par fournisseur (L5-T2), restreint aux blocs d'un
    chantier donné (`chantier_id=None` sélectionne le chantier non résolu,
    même principe qu'un `chantier_id=None` en sortie de
    `bilan_par_chantier`, décision du contrôleur). Les blocs sans
    fournisseur résolu sont regroupés sous une ligne `fournisseur_id=None`,
    jamais ignorés (même règle que pour le chantier). Voir
    `_bilan_par_fournisseur_interne` pour la construction (partagée avec la
    vue inverse)."""
    return await _bilan_par_fournisseur_interne(
        session,
        mois=mois,
        agence=agence,
        filtre_perimetre=lambda blocs: _condition_exact_ou_nul(
            blocs.c.chantier_id, chantier_id
        ),
        filtre_anomalies=lambda anomalies: _condition_exact_ou_nul(
            anomalies.c.chantier_id, chantier_id
        ),
    )


async def bilan_par_fournisseur_global(
    session: AsyncSession,
    *,
    mois: date | None,
    agence: str | None,
) -> list[LigneBilanFournisseur]:
    """Vue inverse (L5-T2), premier niveau : bilan agrégé par fournisseur
    sur l'ensemble des chantiers -- même construction que
    `bilan_par_fournisseur` (`_bilan_par_fournisseur_interne`), sans filtre
    de périmètre par chantier. Point d'entrée de la navigation « du
    fournisseur vers le chantier »."""
    return await _bilan_par_fournisseur_interne(
        session,
        mois=mois,
        agence=agence,
        filtre_perimetre=None,
        filtre_anomalies=None,
    )


async def bilan_par_bl(
    session: AsyncSession,
    *,
    chantier_id: uuid.UUID | None,
    fournisseur_id: uuid.UUID | None,
    mois: date | None,
) -> list[LigneBilanBl]:
    """Bilan agrégé au niveau BL (L5-T2) : une ligne par bloc de facture
    (« Concerne le B.L. n°... »), restreint à un chantier et un fournisseur
    donnés (`None` sélectionne le côté non résolu de chacun, même principe
    que les deux niveaux précédents). Le niveau BL est le bloc, pas le
    document BL (décision du contrôleur) : c'est le bloc qui porte le
    montant facturé. Pas de paramètre `agence` (absent de la fiche pour ce
    niveau -- le chantier est déjà fixé par `chantier_id`, l'agence n'y
    ajoute aucune restriction supplémentaire).

    Même construction que les deux niveaux précédents
    (`_sous_requete_blocs`/`_sous_requete_anomalies`/
    `_expressions_montants`), mais groupée sur l'identité du bloc lui-même
    (déjà la granularité de `_sous_requete_blocs`) plutôt que sur un
    référentiel joint : chaque groupe ne contient donc jamais plus d'une
    ligne `blocs` et au plus une ligne `anomalies` -- l'agrégat `func.sum`
    d'un groupe à une seule ligne renvoie simplement cette ligne."""
    blocs = _sous_requete_blocs(_conditions_base(mois))
    anomalies = _sous_requete_anomalies(mois)
    anomalies_qte_prix = _anomalies_qte_prix_par_bloc(anomalies)
    comptes_anomalies = _comptes_anomalies(anomalies, anomalies.c.bloc_id)
    montants = _expressions_montants(
        blocs, anomalies_qte_prix, comptes_anomalies.c.nb_total
    )

    requete = (
        select(
            blocs.c.bloc_id,
            blocs.c.numero_bl,
            blocs.c.date_bl,
            blocs.c.statut_rapprochement,
            blocs.c.bl_document_id,
            blocs.c.facture_id,
            montants.facture_ht.label("facture_ht"),
            montants.rapproche.label("rapproche"),
            montants.en_ecart.label("en_ecart"),
            montants.non_justifie.label("non_justifie"),
            montants.nb_anomalies_ouvertes.label("nb_anomalies_ouvertes"),
        )
        .select_from(blocs)
        .outerjoin(anomalies_qte_prix, anomalies_qte_prix.c.bloc_id == blocs.c.bloc_id)
        .outerjoin(comptes_anomalies, comptes_anomalies.c.bloc_id == blocs.c.bloc_id)
        .group_by(
            blocs.c.bloc_id,
            blocs.c.numero_bl,
            blocs.c.date_bl,
            blocs.c.statut_rapprochement,
            blocs.c.bl_document_id,
            blocs.c.facture_id,
            comptes_anomalies.c.nb_total,
        )
        .where(
            _condition_exact_ou_nul(blocs.c.chantier_id, chantier_id),
            _condition_exact_ou_nul(blocs.c.fournisseur_id, fournisseur_id),
        )
        .order_by(
            montants.facture_ht.desc(),
            blocs.c.numero_bl.asc(),
            blocs.c.bloc_id.asc(),
        )
    )

    lignes = (await session.execute(requete)).all()
    return [
        LigneBilanBl(
            bloc_id=ligne.bloc_id,
            numero_bl=ligne.numero_bl,
            date_bl=ligne.date_bl,
            statut_rapprochement=ligne.statut_rapprochement,
            bl_document_id=ligne.bl_document_id,
            facture_id=ligne.facture_id,
            montants=_montants_bilan(ligne),
        )
        for ligne in lignes
    ]


# --------------------------------------------------------------------------
# Export détaillé (décision d'Ilane du 23/09/2026, réponse à Q3 du lot 5) :
# une ligne par ligne de facture, sur tout le périmètre `mois`/`agence`.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LigneBilanDetail:
    """Une ligne de l'export détaillé du bilan : une ligne de facture
    (`ligne`), pas un agrégat -- le pendant « une ligne par ligne de
    facture » des cinq niveaux ci-dessus (décision d'Ilane du 23/09/2026,
    réponse à Q3 du lot 5, `docs/lot-5-recette.md` §4). `chantier_id`/
    `nom_chantier`/`agence` valent `None` pour les blocs dont le chantier
    n'a pas pu être résolu, jamais éliminés (même principe que
    `LigneBilanChantier.chantier_id`) ; `fournisseur_id`/`fournisseur_nom`
    suivent la même règle pour le fournisseur.

    `qte_facturee`/`unite` sont les valeurs brutes de la ligne
    (`ligne.qte_totale`/`ligne.unite_brut`) -- ce que porte le document, pas
    la quantité convertie en unité de facturation (`ligne.qte_fact`, L4-D7,
    écrite par `rapprocher_facture` pour comparer deux lignes dont les
    unités diffèrent) : ce fichier reproduit le document, pas une
    conversion interne au moteur de règles (décision du contrôleur, à
    signaler si elle se révèle fausse). `qte_bl_appariee` est la même
    colonne brute lue sur la ligne de BL appariée par `rapprochement_ligne`
    (`ingest.rapprochement`, L4-T7 -- une ligne de facture est appariée à au
    plus une ligne de BL par construction), `None` si aucun appariement.

    `nb_anomalies_ouvertes`/`codes_regles` portent les anomalies ouvertes
    qui concernent cette ligne précise (`Anomalie.ligne_id`) ou tout son
    bloc quand l'anomalie n'a pas de ligne propre (`Anomalie.bloc_id`, ex.
    R01/R02) -- jamais recalculés par un JOIN direct sur `ligne`/`anomalie`
    (voir `bilan_detail`). R06 (« ligne du BL non facturée ») ne peut jamais
    y figurer : elle porte `ligne_id` sur la ligne de BL absente de la
    facture, jamais sur une ligne de ce périmètre ni `None` (limite
    documentée dans `docs/dette.md`)."""

    ligne_id: uuid.UUID
    bloc_id: uuid.UUID
    facture_id: uuid.UUID
    mois: date
    fournisseur_id: uuid.UUID | None
    fournisseur_nom: str | None
    numero_facture: str | None
    date_facture: date | None
    chantier_id: uuid.UUID | None
    nom_chantier: str | None
    agence: str | None
    numero_bl: str | None
    statut_rapprochement: str | None
    type_ligne: str
    code_article: str | None
    designation: str | None
    qte_facturee: Decimal | None
    unite: str | None
    pu_ht: Decimal | None
    remise_pct: Decimal | None
    montant_ht: Decimal | None
    qte_bl_appariee: Decimal | None
    nb_anomalies_ouvertes: int
    codes_regles: tuple[str, ...]


def _mois_ligne(date_doc: date | None, created_at: datetime) -> date:
    """Le mois d'une ligne de facture (L5-D4, même définition que
    `_condition_mois` ci-dessus, calculée ici en Python plutôt qu'en SQL :
    une seule colonne à convertir par ligne déjà chargée, pas un filtre) :
    celui de sa facture (`date_doc`), sinon `created_at` (garanti non nul,
    colonne `NOT NULL`) converti en Europe/Paris. Renvoie le 1er du mois
    résolu, comme `_condition_mois`."""
    if date_doc is not None:
        return date(date_doc.year, date_doc.month, 1)
    instant_paris = created_at.astimezone(FUSEAU_PARIS)
    return date(instant_paris.year, instant_paris.month, 1)


async def _anomalies_par_ligne_et_bloc(
    session: AsyncSession,
    *,
    ids_lignes: set[uuid.UUID],
    ids_blocs: set[uuid.UUID],
) -> tuple[dict[uuid.UUID, tuple[str, ...]], dict[uuid.UUID, tuple[str, ...]]]:
    """Codes de règle des anomalies ouvertes attribuables à chacune des
    lignes/blocs déjà bornés par `bilan_detail` (`ids_lignes`/`ids_blocs`) --
    jamais un JOIN sur `ligne`/`blocs` (voir le docstring de `bilan_detail` :
    un JOIN direct multiplierait les lignes renvoyées par leurs anomalies).
    Une anomalie ouverte portant `ligne_id` concerne cette ligne précise
    (R03/R04/R05/R07/R08/R09/R13/R17, toujours rattachées par
    `rapprocher_facture` à une ligne de facture du périmètre, Ruling L5-R3) ;
    une anomalie ouverte sans `ligne_id` dont le `bloc_id` est dans le
    périmètre concerne tout le bloc (R01/R02, qui ne portent jamais sur une
    ligne précise). Une anomalie portant un `ligne_id` étranger au périmètre
    (R06, dont `ligne_id` désigne la ligne de BL absente de la facture,
    jamais une ligne de facture) n'entre dans aucun des deux dictionnaires,
    même si son `bloc_id` y est (limite documentée dans `docs/dette.md`)."""
    if not ids_lignes and not ids_blocs:
        return {}, {}
    requete = select(Anomalie.ligne_id, Anomalie.bloc_id, Anomalie.regle).where(
        Anomalie.statut == "ouverte",
        or_(
            Anomalie.ligne_id.in_(ids_lignes),
            and_(Anomalie.ligne_id.is_(None), Anomalie.bloc_id.in_(ids_blocs)),
        ),
    )
    resultat = (await session.execute(requete)).all()
    par_ligne: dict[uuid.UUID, list[str]] = {}
    par_bloc: dict[uuid.UUID, list[str]] = {}
    for ligne_id, bloc_id, regle in resultat:
        if ligne_id is not None:
            par_ligne.setdefault(ligne_id, []).append(regle)
        elif bloc_id is not None:
            par_bloc.setdefault(bloc_id, []).append(regle)
    return (
        {cle: tuple(valeurs) for cle, valeurs in par_ligne.items()},
        {cle: tuple(valeurs) for cle, valeurs in par_bloc.items()},
    )


async def bilan_detail(
    session: AsyncSession,
    *,
    mois: date | None,
    agence: str | None,
) -> list[LigneBilanDetail]:
    """Export détaillé du bilan (décision d'Ilane du 23/09/2026, réponse à
    Q3 du lot 5) : une ligne par ligne de facture (tous types --
    `article`/`eco`/`commentaire`, rien n'est tu au client qui ouvre ce
    fichier dans Excel), sur tout le périmètre filtré (mêmes filtres
    `mois`/`agence` que les cinq niveaux ci-dessus, jamais un second calcul
    du chantier ou du mois). Réutilise `_sous_requete_blocs`/
    `_conditions_base`/`_condition_agence` (même résolution du chantier --
    `COALESCE(bloc_facture.chantier_id, document.chantier_id)` -- et même
    chantier non résolu conservé sous `chantier_id=None`, jamais éliminé
    silencieusement, même principe que les cinq niveaux ci-dessus).

    Chaque `Ligne` d'une facture appartient toujours à un bloc
    (`deposer_facture`, lots 2/3) : une simple jointure interne
    `Ligne.bloc_id == blocs.c.bloc_id` (clé de la sous-requête, un groupe
    par bloc) rattache chaque ligne à son bloc sans dupliquer aucune ligne
    ni en perdre -- `blocs` filtre déjà `Document.type == "facture"`, donc
    une ligne de BL (toujours `bloc_id=None`) n'est jamais sélectionnée.

    Piège évité (décision du contrôleur, signalé par la fiche de tâche) :
    les anomalies ne sont **jamais** jointes directement sur `ligne`/
    `blocs` -- un JOIN direct multiplierait les lignes par leurs anomalies
    (une ligne portant deux anomalies ouvertes sortirait deux fois),
    faussant jusqu'au nombre de lignes renvoyées. La portée de chaque
    anomalie ouverte du périmètre est donc lue séparément
    (`_anomalies_par_ligne_et_bloc`, une seule requête supplémentaire,
    jamais une par ligne) puis recomposée en Python, une fois par ligne.

    `qte_bl_appariee` vient de `rapprochement_ligne` (`ingest.rapprochement`,
    L4-T7) : `None` si la ligne n'a été appariée à aucune ligne de BL.

    Tri déterministe : chantier (nom, puis identifiant -- les chantiers non
    résolus, `NULL`, se départagent en dernier, ordre `NULLS LAST` par
    défaut de PostgreSQL en tri ascendant), fournisseur (même principe),
    numéro de facture, numéro de BL, bloc, puis ordre de la ligne sur son
    bloc et enfin son identifiant (dernier départage absolu)."""
    blocs = _sous_requete_blocs(_conditions_base(mois))
    bl_ligne = aliased(Ligne)

    requete = (
        select(
            Ligne.id.label("ligne_id"),
            blocs.c.bloc_id,
            blocs.c.facture_id,
            Document.date_doc,
            Document.created_at,
            Document.numero.label("numero_facture"),
            blocs.c.chantier_id,
            Chantier.nom_canonique,
            Chantier.agence,
            blocs.c.fournisseur_id,
            Fournisseur.nom.label("fournisseur_nom"),
            blocs.c.numero_bl,
            blocs.c.statut_rapprochement,
            Ligne.type_ligne,
            Ligne.code_brut,
            Ligne.article_brut,
            Ligne.qte_totale,
            Ligne.unite_brut,
            Ligne.pu_ht,
            Ligne.remise_pct,
            Ligne.montant_ht,
            bl_ligne.qte_totale.label("qte_bl_appariee"),
        )
        .select_from(Ligne)
        .join(blocs, blocs.c.bloc_id == Ligne.bloc_id)
        .join(Document, Document.id == blocs.c.facture_id)
        .outerjoin(Chantier, Chantier.id == blocs.c.chantier_id)
        .outerjoin(Fournisseur, Fournisseur.id == blocs.c.fournisseur_id)
        .outerjoin(RapprochementLigne, RapprochementLigne.ligne_facture_id == Ligne.id)
        .outerjoin(bl_ligne, bl_ligne.id == RapprochementLigne.ligne_bl_id)
    )
    if agence is not None:
        requete = requete.where(_condition_agence(blocs, agence))

    requete = requete.order_by(
        Chantier.nom_canonique.asc(),
        blocs.c.chantier_id.asc(),
        Fournisseur.nom.asc(),
        blocs.c.fournisseur_id.asc(),
        Document.numero.asc(),
        blocs.c.numero_bl.asc(),
        blocs.c.bloc_id.asc(),
        Ligne.ordre.asc(),
        Ligne.id.asc(),
    )

    lignes = (await session.execute(requete)).all()

    ids_lignes = {ligne.ligne_id for ligne in lignes}
    ids_blocs = {ligne.bloc_id for ligne in lignes}
    anomalies_par_ligne, anomalies_par_bloc = await _anomalies_par_ligne_et_bloc(
        session, ids_lignes=ids_lignes, ids_blocs=ids_blocs
    )

    resultat: list[LigneBilanDetail] = []
    for ligne in lignes:
        codes_ligne = anomalies_par_ligne.get(ligne.ligne_id, ())
        codes_bloc = anomalies_par_bloc.get(ligne.bloc_id, ())
        resultat.append(
            LigneBilanDetail(
                ligne_id=ligne.ligne_id,
                bloc_id=ligne.bloc_id,
                facture_id=ligne.facture_id,
                mois=_mois_ligne(ligne.date_doc, ligne.created_at),
                fournisseur_id=ligne.fournisseur_id,
                fournisseur_nom=ligne.fournisseur_nom,
                numero_facture=ligne.numero_facture,
                date_facture=ligne.date_doc,
                chantier_id=ligne.chantier_id,
                nom_chantier=ligne.nom_canonique,
                agence=ligne.agence,
                numero_bl=ligne.numero_bl,
                statut_rapprochement=ligne.statut_rapprochement,
                type_ligne=ligne.type_ligne,
                code_article=ligne.code_brut,
                designation=ligne.article_brut,
                qte_facturee=ligne.qte_totale,
                unite=ligne.unite_brut,
                pu_ht=ligne.pu_ht,
                remise_pct=ligne.remise_pct,
                montant_ht=ligne.montant_ht,
                qte_bl_appariee=ligne.qte_bl_appariee,
                nb_anomalies_ouvertes=len(codes_ligne) + len(codes_bloc),
                codes_regles=tuple(sorted(set(codes_ligne) | set(codes_bloc))),
            )
        )
    return resultat
