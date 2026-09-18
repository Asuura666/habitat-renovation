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
(décision du contrôleur), et utilisée à deux endroits : pour `en_ecart`
et pour `MontantsBilan.nb_anomalies_ouvertes`. Point non couvert par la
fiche/L5-D3 (qui ne définit que les quatre montants) : voir le doute
consigné dans `L5-T1-report.md` sur le choix de compter ici uniquement les
anomalies de ce même ensemble (cohérent avec `en_ecart`), plutôt que la
totalité des anomalies ouvertes du chantier via
`ingest.anomalies.CHANTIER_ID_RESOLU` (qui, pour R07/R08/R09, ne porte
jamais `Anomalie.bloc_id` — seulement `ligne_id`/`article_id` — et
résoudrait donc ces trois règles sur `Document.chantier_id`, presque
toujours `NULL` pour une facture ; réutiliser `CHANTIER_ID_RESOLU` tel quel
aurait donc silencieusement fait disparaître la moitié de l'ensemble
`REGLES_QUANTITE_OU_PRIX` de ce compte). La résolution du bloc d'une
anomalie ci-dessous (`bloc_id_anomalie`, dans `bilan_par_chantier`) contourne
ce trou en retombant sur `Ligne.bloc_id` via `Anomalie.ligne_id` quand
`Anomalie.bloc_id` est absent.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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
    d'anomalies ouvertes de quantité/prix qui s'y rattachent — tous des
    `Decimal` sauf le compte (jamais de `float`, CLAUDE.md)."""

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


@dataclass
class _Accumulateur:
    """Accumulateur mutable interne, un par chantier (y compris
    `chantier_id=None`) — jamais exposé, converti en `MontantsBilan` gelé en
    fin de fonction."""

    facture_ht: Decimal = Decimal("0")
    rapproche: Decimal = Decimal("0")
    en_ecart: Decimal = Decimal("0")
    non_justifie: Decimal = Decimal("0")
    nb_anomalies_ouvertes: int = 0


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
    où l'appelant ne transmettrait pas strictement un 1er du mois)."""
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
    puis par nom de chantier (ordre stable entre deux appels, décision du
    contrôleur) — la ligne `chantier_id=None` (blocs sans chantier résolu)
    se départage en dernier à montant égal (`nom_canonique` absent).

    Deux requêtes agrégées (même principe que
    `rapprochement._construire_historiques`/`suivi._chantiers_suivis` :
    une requête par grandeur, combinées en Python plutôt qu'un unique gros
    JOIN — un JOIN direct entre `ligne` et `anomalie` sur le même bloc
    multiplierait les lignes de chacun par l'autre et fausserait les
    sommes) :

    1. une ligne par bloc du périmètre (facture non archivée, mois filtré
       si fourni) : chantier résolu, statut de rapprochement, montant HT
       (somme des lignes "article"/"eco" du bloc, `0` si aucune) ;
    2. une ligne par bloc portant au moins une anomalie **ouverte** de
       `REGLES_QUANTITE_OU_PRIX` : nombre de ces anomalies.

    Un bloc de facture archivée n'entre dans aucun montant (`Document.statut
    != "archive"`, même formulation que le lot 4)."""
    conditions: list[Any] = [
        Document.type == "facture",
        Document.statut != "archive",
    ]
    if mois is not None:
        conditions.append(_condition_mois(mois))

    chantier_du_bloc = func.coalesce(BlocFacture.chantier_id, Document.chantier_id)

    lignes_par_bloc = (
        await session.execute(
            select(
                BlocFacture.id,
                chantier_du_bloc,
                BlocFacture.statut_rapprochement,
                func.coalesce(func.sum(Ligne.montant_ht), Decimal("0")),
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
        )
    ).all()

    if not lignes_par_bloc:
        return []

    bloc_ids = [bloc_id for bloc_id, *_ in lignes_par_bloc]

    # Bloc d'une anomalie de quantité/prix (voir docstring de module) :
    # `Anomalie.bloc_id` d'abord (porté par R03-R06), sinon celui de la
    # ligne de facture visée par `Anomalie.ligne_id` (seul champ que portent
    # R07/R08/R09) -- sans ce repli, ces trois règles resteraient sans bloc
    # résolu et disparaîtraient du décompte.
    ligne_anomalie = aliased(Ligne)
    bloc_id_anomalie = func.coalesce(Anomalie.bloc_id, ligne_anomalie.bloc_id)

    lignes_anomalies = (
        await session.execute(
            select(bloc_id_anomalie, func.count())
            .select_from(Anomalie)
            .outerjoin(ligne_anomalie, ligne_anomalie.id == Anomalie.ligne_id)
            .where(
                Anomalie.statut == "ouverte",
                Anomalie.regle.in_(tuple(REGLES_QUANTITE_OU_PRIX)),
                bloc_id_anomalie.in_(bloc_ids),
            )
            .group_by(bloc_id_anomalie)
        )
    ).all()
    nb_anomalies_par_bloc: dict[uuid.UUID, int] = {
        bloc_id: nb for bloc_id, nb in lignes_anomalies if bloc_id is not None
    }

    accumulateurs: dict[uuid.UUID | None, _Accumulateur] = {}
    for bloc_id, chantier_id, statut, montant in lignes_par_bloc:
        accumulateur = accumulateurs.setdefault(chantier_id, _Accumulateur())
        accumulateur.facture_ht += montant
        if statut == "recu":
            accumulateur.rapproche += montant
        if statut in _STATUTS_NON_JUSTIFIE:
            accumulateur.non_justifie += montant
        nb_anomalies = nb_anomalies_par_bloc.get(bloc_id, 0)
        accumulateur.nb_anomalies_ouvertes += nb_anomalies
        if nb_anomalies > 0:
            accumulateur.en_ecart += montant

    chantier_ids = [
        chantier_id for chantier_id in accumulateurs if chantier_id is not None
    ]
    chantiers_map: dict[uuid.UUID, Chantier] = {}
    if chantier_ids:
        chantiers_db: Sequence[Chantier] = (
            (
                await session.execute(
                    select(Chantier).where(Chantier.id.in_(chantier_ids))
                )
            )
            .scalars()
            .all()
        )
        chantiers_map = {chantier.id: chantier for chantier in chantiers_db}

    resultat: list[LigneBilanChantier] = []
    for chantier_id, accumulateur in accumulateurs.items():
        chantier = chantiers_map.get(chantier_id) if chantier_id is not None else None
        chantier_agence = chantier.agence if chantier is not None else None
        if agence is not None and chantier_agence != agence:
            continue
        resultat.append(
            LigneBilanChantier(
                chantier_id=chantier_id,
                nom_canonique=chantier.nom_canonique if chantier is not None else None,
                agence=chantier_agence,
                montants=MontantsBilan(
                    facture_ht=accumulateur.facture_ht,
                    rapproche=accumulateur.rapproche,
                    en_ecart=accumulateur.en_ecart,
                    non_justifie=accumulateur.non_justifie,
                    nb_anomalies_ouvertes=accumulateur.nb_anomalies_ouvertes,
                ),
            )
        )

    resultat.sort(
        key=lambda ligne: (
            -ligne.montants.facture_ht,
            ligne.nom_canonique is None,
            ligne.nom_canonique or "",
        )
    )
    return resultat
