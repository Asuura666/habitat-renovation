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
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.models import Anomalie, BlocFacture, Chantier, Document, Ligne

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
    traiter. Les anomalies de document entier (R10/R11), jamais rattachées
    à un bloc précis, n'entrent dans aucun des deux champs."""

    facture_ht: Decimal
    rapproche: Decimal
    en_ecart: Decimal
    non_justifie: Decimal
    nb_anomalies_ouvertes: int


@dataclass(frozen=True)
class LigneBilanChantier:
    """Une ligne du bilan au niveau chantier. `chantier_id=None` regroupe
    les blocs dont le chantier n'a pas pu être résolu (décision du
    contrôleur) : `nom_canonique`/`agence` valent alors `None`, c'est au
    front de nommer cette ligne (L5-T4/T5, hors de cette tâche)."""

    chantier_id: uuid.UUID | None
    nom_canonique: str | None
    agence: str | None
    montants: MontantsBilan


def _premier_jour_mois_suivant(premier_jour: date) -> date:
    """Premier jour du mois calendaire suivant `premier_jour` (qui doit
    déjà être un 1er du mois) — calcul en stdlib pur, comme
    `rapprochement._six_mois_avant`."""
    if premier_jour.month == 12:
        return date(premier_jour.year + 1, 1, 1)
    return date(premier_jour.year, premier_jour.month + 1, 1)


def _condition_mois(mois: date) -> Any:
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
            Document.date_doc.is_not(None),
            Document.date_doc >= premier_jour,
            Document.date_doc < jour_suivant,
        ),
        and_(
            Document.date_doc.is_(None),
            Document.created_at >= debut_instant,
            Document.created_at < fin_instant,
        ),
    )


async def bilan_par_chantier(
    session: AsyncSession,
    *,
    mois: date | None,
    agence: str | None,
) -> list[LigneBilanChantier]:
    """Bilan agrégé par chantier (L5-T1), trié par `facture_ht` décroissant
    puis par nom de chantier puis par `chantier_id` (tour de correction 1 :
    dernière clé de tri, pour que deux chantiers de même nom et de même
    montant ne s'échangent jamais d'un appel à l'autre) — la ligne
    `chantier_id=None` (blocs sans chantier résolu) se départage en dernier
    à montant égal (`nom_canonique` absent, Postgres place les `NULL` en
    dernier pour un tri ascendant par défaut).

    Deux sous-requêtes agrégées, combinées et triées par la requête
    elle-même (tour de correction 1 : jamais un tri Python sur une liste
    déjà construite) :

    1. `blocs` : une ligne par bloc du périmètre (facture non archivée,
       mois filtré si fourni) — chantier résolu, statut de rapprochement,
       montant HT (somme des lignes "article"/"eco" du bloc, `0` si
       aucune) ;
    2. `anomalies` : une ligne par bloc portant au moins une anomalie
       **ouverte**, avec deux comptes côte à côte (`FILTER`, clause SQL
       standard sur une fonction d'agrégat) : le total (Ruling L5-R4) et le
       sous-ensemble `REGLES_QUANTITE_OU_PRIX` (matière de `en_ecart`).

    Les deux ne sont jamais jointes directement à `ligne` dans la même
    requête : un JOIN direct entre `ligne` et `anomalie` sur le même bloc
    multiplierait les lignes de chacun par l'autre et fausserait les
    sommes — chacune est d'abord agrégée par bloc dans sa propre
    sous-requête (même principe que `rapprochement._construire_historiques`
    / `suivi._chantiers_suivis`), puis les deux sont jointes 1-à-1 par
    `bloc_id` avant l'agrégation finale par chantier.

    Un bloc de facture archivée n'entre dans aucun montant (`Document.statut
    != "archive"`, même formulation que le lot 4)."""
    conditions: list[Any] = [
        Document.type == "facture",
        Document.statut != "archive",
    ]
    if mois is not None:
        conditions.append(_condition_mois(mois))

    blocs = (
        select(
            BlocFacture.id.label("bloc_id"),
            func.coalesce(BlocFacture.chantier_id, Document.chantier_id).label(
                "chantier_id"
            ),
            BlocFacture.statut_rapprochement.label("statut_rapprochement"),
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
            BlocFacture.statut_rapprochement,
        )
        .subquery()
    )

    # `Anomalie.bloc_id` est toujours renseigné depuis le Ruling L5-R3 pour
    # toute anomalie de facture rattachée à une ligne -- R10/R11 (contrôles
    # de document entier, jamais rattachés à un bloc) restent donc hors de
    # ce compte : une anomalie sur la totalité de la facture n'appartient à
    # aucun chantier précis.
    anomalies = (
        select(
            Anomalie.bloc_id.label("bloc_id"),
            func.count().label("nb_total"),
            func.count()
            .filter(Anomalie.regle.in_(tuple(REGLES_QUANTITE_OU_PRIX)))
            .label("nb_qte_prix"),
        )
        .where(Anomalie.statut == "ouverte", Anomalie.bloc_id.is_not(None))
        .group_by(Anomalie.bloc_id)
        .subquery()
    )

    facture_ht = func.sum(blocs.c.montant_ht)
    rapproche = func.sum(
        case((blocs.c.statut_rapprochement == "recu", blocs.c.montant_ht), else_=0)
    )
    en_ecart = func.sum(
        case(
            (func.coalesce(anomalies.c.nb_qte_prix, 0) > 0, blocs.c.montant_ht),
            else_=0,
        )
    )
    non_justifie = func.sum(
        case(
            (
                blocs.c.statut_rapprochement.in_(_STATUTS_NON_JUSTIFIE),
                blocs.c.montant_ht,
            ),
            else_=0,
        )
    )
    nb_anomalies_ouvertes = func.coalesce(
        func.sum(func.coalesce(anomalies.c.nb_total, 0)), 0
    )

    requete = (
        select(
            Chantier.id,
            Chantier.nom_canonique,
            Chantier.agence,
            facture_ht.label("facture_ht"),
            rapproche.label("rapproche"),
            en_ecart.label("en_ecart"),
            non_justifie.label("non_justifie"),
            nb_anomalies_ouvertes.label("nb_anomalies_ouvertes"),
        )
        .select_from(blocs)
        .outerjoin(anomalies, anomalies.c.bloc_id == blocs.c.bloc_id)
        .outerjoin(Chantier, Chantier.id == blocs.c.chantier_id)
        .group_by(Chantier.id, Chantier.nom_canonique, Chantier.agence)
    )
    if agence is not None:
        requete = requete.where(Chantier.agence == agence)

    requete = requete.order_by(
        facture_ht.desc(), Chantier.nom_canonique.asc(), Chantier.id.asc()
    )

    lignes = (await session.execute(requete)).all()
    return [
        LigneBilanChantier(
            chantier_id=chantier_id,
            nom_canonique=nom_canonique,
            agence=chantier_agence,
            montants=MontantsBilan(
                facture_ht=montant_facture_ht,
                rapproche=montant_rapproche,
                en_ecart=montant_en_ecart,
                non_justifie=montant_non_justifie,
                nb_anomalies_ouvertes=nb_anomalies,
            ),
        )
        for (
            chantier_id,
            nom_canonique,
            chantier_agence,
            montant_facture_ht,
            montant_rapproche,
            montant_en_ecart,
            montant_non_justifie,
            nb_anomalies,
        ) in lignes
    ]
