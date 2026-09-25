"""Tableau de bord du mois (`ingest/tableau_de_bord.py`, refonte front T2) —
voir `docs/superpowers/specs/2026-09-23-refonte-front-design.md` §6.2 :
totaux du mois, problèmes ouverts/urgents, BL reçus/facturés, lignes
chantier enrichies d'un état calculé et les problèmes prioritaires. Aucun
calcul ni tri de ce genre ne doit être refait côté front (même principe que
`ingest/bilan.py`, L5-D1) : ce module ne fait qu'assembler des agrégats déjà
calculés par `ingest.bilan`/`ingest.anomalies`, jamais un second calcul
divergent.

`mois` est ramené au 1er du mois dès l'entrée du service (revue finale de
la refonte du front, constat SERVEUR-7) : `TableauDeBord.mois` vaut donc
toujours un 1er du mois, quel que soit le jour transmis par l'appelant.

`totaux` (L5-D3, `ingest.bilan.MontantsBilan`) : simple somme des montants
des lignes de `bilan_par_chantier(mois=mois, agence=None)` — les quatre
montants existants ne changent pas de définition ici. `conforme` est la
somme des `MontantsBilan.conforme` des chantiers (revue finale de la
refonte du front, constat SERVEUR-2) : calculé bloc par bloc par
`ingest.bilan` (blocs reçus sans anomalie ouverte de quantité/prix), plus
jamais par la formule `rapproche - en_ecart` de la spec §6.2, qui supposait
à tort que tout bloc en écart était reçu (R07-R09 s'évaluent quel que soit
l'état du BL).

`nb_bl_factures`/`nb_bl_recus`/`nb_bl_manquants` : comptés directement sur
la sous-requête `_sous_requete_blocs`/`_conditions_base` d'`ingest.bilan`
(mêmes conditions de mois que le bilan, jamais une seconde définition de
"quel bloc appartient à ce mois"). `nb_bl_manquants` (revue finale,
constats SERVEUR-1/COUVERTURE-4) : blocs `non_recu` qui portent encore une
anomalie ouverte de bon manquant -- les seuls bons réellement « à
réclamer ». Un bloc `pas_de_bon` n'a par définition aucun bon à réclamer,
et un bon dont le problème a été contesté ou ignoré n'est plus à réclamer :
la soustraction `nb_bl_factures - nb_bl_recus`, autrefois faite par le
front, comptait les deux.

Anomalies ouvertes du mois (correction de revue, fix round 1 -- décision du
contrôleur qui prime sur la règle de filtrage du brief, spec §6.2 "jamais un
second calcul divergent") : la portée exacte vient d'`ingest.bilan
._sous_requete_anomalies(mois)`, la même sous-requête que celle qui calcule
`MontantsBilan.nb_anomalies_ouvertes` par chantier (Ruling L5-R4) -- une
anomalie de bloc suit le mois de sa facture, une anomalie de document son
propre mois, une anomalie sans les deux `Anomalie.created_at`, les
documents archivés exclus. Ses identifiants sont ensuite relus par
`lister_anomalies(ids=..., limite=len(ids))` (voir `_anomalies_ouvertes_du_
mois` ci-dessous) pour obtenir leur forme `AnomalieLue` complète.
`nb_problemes_ouverts`/`nb_problemes_urgents` et les `priorites` sont tous
les trois dérivés de cette même liste, jamais recalculés séparément ; `etat`
en dérive aussi (groupée par chantier).

Périmètre de `nb_problemes_ouverts` (revue finale, constat SERVEUR-7) : il
compte **toutes** les anomalies ouvertes du mois, y compris celles qu'aucune
ligne du tableau `chantiers` ne porte -- une anomalie sans chantier, sans
bloc et sans document (retirée du compte par chantier par
`ingest.bilan._filtre_anomalies_portee`), ou celle d'un chantier qui n'a
aucune facture ce mois-ci (R16, par exemple). La tuile peut donc dépasser la
somme de la colonne « Problèmes » des chantiers : ce n'est pas une
incohérence, c'est une portée plus large, écrite ici noir sur blanc.

`etat` d'un chantier (ordre de priorité strict) : `chantier_id is None` ->
`a_rattacher` ; une anomalie **ouverte** du chantier de catégorie « bon
manquant » (R01/R02, `ingest.anomalies.CATEGORIES_REGLE`) -> `bl_manquant` ;
de catégorie « prix » -> `prix` ; de catégorie « quantités » -> `quantites` ;
`nb_anomalies_ouvertes > 0` (déjà calculé par `ingest.bilan`, Ruling
L5-R4 : toutes les anomalies ouvertes du chantier) -> `a_voir` ; sinon
`conforme`. Revue finale de la refonte du front (constats SERVEUR-1 et
SERVEUR-3) : `bl_manquant` reposait sur `non_justifie > 0`, un montant
calculé à partir du seul statut du bloc -- un problème de bon manquant déjà
contesté ou ignoré laissait le chantier en rouge « BL manquant » avec zéro
problème ouvert ; et les ensembles « prix »/« quantités » étaient une
seconde table divergente de celle du front. Les trois états viennent
désormais de la même liste d'anomalies ouvertes et de la même table de
catégories que les filtres de l'écran « À régler ». `a_voir` est la
sixième valeur de `ETATS`, en plus des cinq états du document de conception
(§6.2, mis à jour) : un chantier dont les seuls problèmes ouverts ne sont ni
un bon manquant, ni un écart de prix ou de quantité (ex. R13 seule).

`a_verifier` d'un chantier : `MontantsBilan.a_verifier`, calculé bloc par
bloc par `ingest.bilan` (blocs portant une anomalie ouverte de bon manquant
ou de quantité/prix, chacun compté une fois) -- plus jamais `en_ecart +
non_justifie`, qui comptait deux fois un bloc non reçu en écart de prix et
gardait un bon déjà réglé.

`montant_en_jeu` d'une priorité (brief T2) : lu directement sur
`AnomalieLue.detail` (jamais recalculé) — `R01`/`R02` portent
`detail["montant_ht"]`, `R05`/`R13` portent `detail["montant"]`, toute
autre règle ou toute valeur non convertible en `Decimal` renvoie `None`
plutôt que de lever. Revue finale (constats ECRAN-8/TELEPHONE-9) : la
valeur est renvoyée **signée**, telle que la porte `detail` -- un avoir
s'affiche donc « -45,00 € » sur l'accueil comme dans l'écran « À régler »,
plus jamais deux signes différents pour le même problème ; seule la clé de
tri en prend la valeur absolue (un avoir de 45 € pèse autant qu'une
facturation de 45 €).

Tri des `priorites` : gravité (haute, moyenne, basse) puis `montant_en_jeu`
en valeur absolue décroissante (`None` en dernier) puis `cree_le` croissant
(même convention que `lister_anomalies`), les quatre premières.

Tri des `chantiers` : `a_verifier` décroissant puis `nom_canonique`
croissant, le chantier non résolu (`nom_canonique is None`) se départageant
en dernier à montant égal — même principe que le tri "dernière clé jamais
ambiguë" d'`ingest.bilan`.

`dernier_mois_facture` (revue finale, constat COUVERTURE-26) : 1er du mois
de la facture non archivée la plus récente (même mois que le bilan : sa
`date_doc`, sinon sa date de dépôt en heure de Paris), `None` sans aucune
facture. Les factures fournisseur sont mensuelles (celle d'août arrive en
septembre) : l'accueil, ouvert par défaut sur le mois courant, peut ainsi
proposer d'aller directement au dernier mois facturé plutôt que d'afficher
des zéros -- valeur fournie par le serveur, jamais devinée par le front.

`nb_bons_recus`/`montant_bons_recus`/`nb_bons_sans_montant` (décision
d'Ilane, 25/09/2026 : la tuile « Écart de quantité » de la Vue d'ensemble
est remplacée par « Montant des bons reçus ») -- l'accueil est construit à
partir des factures ; un bon validé mais pas encore retrouvé sur une
facture n'y apparaissait nulle part, alors qu'Ilane veut voir tout de suite
ce qui a été livré, facture ou non. `nb_bons_recus` compte les documents de
type bon (`ingest.lecture.TYPES_BL` : « bl » et « enlevement », même
constante que le reste du module) au statut `recu` du mois affiché --
jamais `a_verifier` (pas encore confirmé) ni `archive` (sorti du suivi
actif). `montant_bons_recus` en somme le `total_ht` (`0` si aucun).
`nb_bons_sans_montant` compte, parmi ces bons reçus, ceux dont `total_ht`
est `NULL` : ils comptent dans `nb_bons_recus` mais jamais dans le montant
-- beaucoup de bons n'ont aucun prix imprimé (le CDC ne l'exige pas), leur
absence de prix ne doit ni gonfler ni fausser `montant_bons_recus`. Un bon
compte qu'il soit ou non déjà retrouvé sur une facture : c'est une notion
différente de `nb_bl_recus`, qui compte des *blocs de facture* rapprochés,
pas des bons. Ni filtre agence (le tableau de bord n'en a pas) ni second
calcul du mois : `_compter_bons_recus` réutilise directement
`ingest.bilan._condition_mois` sur `Document` (`date_doc`, sinon
`created_at` converti en Europe/Paris, L5-D4), jamais une nouvelle
définition de "quel bon appartient à ce mois".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.anomalies import AnomalieLue, categorie_regle, lister_anomalies
from app.modules.ingest.bilan import (
    LigneBilanChantier,
    MontantsBilan,
    _anomalies_qte_prix_par_bloc,
    _condition_mois,
    _conditions_base,
    _sous_requete_anomalies,
    _sous_requete_blocs,
    bilan_par_chantier,
)
from app.modules.ingest.lecture import TYPES_BL
from app.modules.ingest.models import Document

Etat = Literal["a_rattacher", "bl_manquant", "prix", "quantites", "a_voir", "conforme"]

ETATS: tuple[Etat, ...] = (
    "a_rattacher",
    "bl_manquant",
    "prix",
    "quantites",
    "a_voir",
    "conforme",
)

# Règles dont `detail` porte un montant chiffré exploitable pour trier les
# priorités (brief T2) -- deux clés différentes selon la règle.
_REGLES_MONTANT_HT = frozenset({"R01", "R02"})
_REGLES_MONTANT = frozenset({"R05", "R13"})

_ORDRE_GRAVITE_PRIORITE: dict[str, int] = {"haute": 0, "moyenne": 1, "basse": 2}

NB_PRIORITES_MAX = 4


@dataclass(frozen=True)
class TotauxMois:
    """Les quatre montants du bilan du mois (L5-D3, somme sur tous les
    chantiers) plus `conforme` -- voir docstring de module."""

    facture_ht: Decimal
    rapproche: Decimal
    en_ecart: Decimal
    non_justifie: Decimal
    conforme: Decimal


@dataclass(frozen=True)
class ChantierTableau:
    """Une ligne du bilan par chantier (`ingest.bilan.LigneBilanChantier`),
    enrichie de l'état calculé et du montant à vérifier -- voir docstring de
    module pour les deux règles de calcul."""

    chantier_id: uuid.UUID | None
    nom_canonique: str | None
    client: str | None
    agence: str | None
    etat: Etat
    montants: MontantsBilan
    a_verifier: Decimal


@dataclass(frozen=True)
class ProblemePrioritaire:
    """Une anomalie ouverte du mois retenue parmi les priorités affichées à
    l'accueil (quatre au plus, voir docstring de module)."""

    anomalie: AnomalieLue
    montant_en_jeu: Decimal | None


@dataclass(frozen=True)
class TableauDeBord:
    """Contenu complet du tableau de bord du mois (`GET
    /api/tableau-de-bord`, refonte front T2) -- voir docstring de module."""

    mois: date
    totaux: TotauxMois
    nb_problemes_ouverts: int
    nb_problemes_urgents: int
    nb_bl_factures: int
    nb_bl_recus: int
    nb_bl_manquants: int
    chantiers: list[ChantierTableau]
    priorites: list[ProblemePrioritaire]
    dernier_mois_facture: date | None
    nb_bons_recus: int
    montant_bons_recus: Decimal
    nb_bons_sans_montant: int


def _montant_en_jeu(anomalie: AnomalieLue) -> Decimal | None:
    """`detail["montant_ht"]` pour R01/R02, `detail["montant"]` (signé)
    pour R05/R13, `None` pour toute autre règle ou toute valeur non
    convertible en `Decimal` (ex. le tiret cadratin `TIRET` des règles
    pures quand la valeur d'origine est absente) -- jamais une exception
    qui interromprait la construction du tableau de bord."""
    if anomalie.regle in _REGLES_MONTANT_HT:
        cle = "montant_ht"
    elif anomalie.regle in _REGLES_MONTANT:
        cle = "montant"
    else:
        return None

    valeur = anomalie.detail.get(cle)
    if valeur is None:
        return None
    try:
        return Decimal(str(valeur))
    except InvalidOperation:
        return None


def _cle_tri_priorite(
    probleme: ProblemePrioritaire,
) -> tuple[int, bool, Decimal, datetime]:
    """Gravité (haute, moyenne, basse) puis `montant_en_jeu` en valeur
    absolue décroissante (`None` en dernier) puis `cree_le` croissant --
    voir docstring de module."""
    montant = probleme.montant_en_jeu
    return (
        _ORDRE_GRAVITE_PRIORITE.get(
            probleme.anomalie.gravite, len(_ORDRE_GRAVITE_PRIORITE)
        ),
        montant is None,
        -abs(montant) if montant is not None else Decimal("0"),
        probleme.anomalie.cree_le,
    )


def _etat_chantier(
    ligne: LigneBilanChantier, anomalies_du_chantier: list[AnomalieLue]
) -> Etat:
    """Ordre de priorité strict -- voir docstring de module."""
    if ligne.chantier_id is None:
        return "a_rattacher"
    categories = {categorie_regle(anomalie.regle) for anomalie in anomalies_du_chantier}
    if "bl" in categories:
        return "bl_manquant"
    if "prix" in categories:
        return "prix"
    if "quantites" in categories:
        return "quantites"
    if ligne.montants.nb_anomalies_ouvertes > 0:
        return "a_voir"
    return "conforme"


def _cle_tri_chantier(chantier: ChantierTableau) -> tuple[Decimal, bool, str]:
    """`a_verifier` décroissant puis `nom_canonique` croissant, le chantier
    non résolu en dernier à montant égal -- voir docstring de module."""
    return (
        -chantier.a_verifier,
        chantier.nom_canonique is None,
        chantier.nom_canonique or "",
    )


async def _anomalies_ouvertes_du_mois(
    session: AsyncSession, *, mois: date
) -> list[AnomalieLue]:
    """Anomalies ouvertes du mois, au sens strict du bilan (correction de
    revue, fix round 1) -- voir docstring de module. Les identifiants
    viennent d'`ingest.bilan._sous_requete_anomalies(mois)`, jamais
    recalculés ici ; `lister_anomalies(ids=..., limite=len(ids))` les relit
    ensuite sous leur forme `AnomalieLue` complète, sans plafond arbitraire
    (la portée est déjà bornée par la sous-requête du mois)."""
    ids_anomalies = (
        (await session.execute(select(_sous_requete_anomalies(mois).c.anomalie_id)))
        .scalars()
        .all()
    )
    if not ids_anomalies:
        return []
    return await lister_anomalies(
        session, statut="ouverte", ids=ids_anomalies, limite=len(ids_anomalies)
    )


async def _compter_blocs(session: AsyncSession, *, mois: date) -> tuple[int, int, int]:
    """`nb_bl_factures`/`nb_bl_recus`/`nb_bl_manquants` -- même sous-requête
    de blocs que `ingest.bilan` (`_sous_requete_blocs`/`_conditions_base`)
    et mêmes comptes d'anomalies ouvertes par bloc
    (`_anomalies_qte_prix_par_bloc`, qui porte `nb_bl_manquant`), jamais une
    seconde définition du périmètre du mois."""
    blocs = _sous_requete_blocs(_conditions_base(mois))
    comptes = _anomalies_qte_prix_par_bloc(_sous_requete_anomalies(mois))
    resultat = (
        await session.execute(
            select(
                func.count().label("nb_bl_factures"),
                func.count()
                .filter(blocs.c.statut_rapprochement == "recu")
                .label("nb_bl_recus"),
                func.count()
                .filter(
                    and_(
                        blocs.c.statut_rapprochement == "non_recu",
                        func.coalesce(comptes.c.nb_bl_manquant, 0) > 0,
                    )
                )
                .label("nb_bl_manquants"),
            )
            .select_from(blocs)
            .outerjoin(comptes, comptes.c.bloc_id == blocs.c.bloc_id)
        )
    ).one()
    return resultat.nb_bl_factures, resultat.nb_bl_recus, resultat.nb_bl_manquants


async def _compter_bons_recus(
    session: AsyncSession, *, mois: date
) -> tuple[int, Decimal, int]:
    """`nb_bons_recus`/`montant_bons_recus`/`nb_bons_sans_montant` -- voir
    docstring de module. Requête directe sur `Document` (bons de livraison
    et bons d'enlèvement, `TYPES_BL`), au statut `recu`, même filtre de
    mois que le reste du tableau de bord (`ingest.bilan._condition_mois`,
    appliqué ici sur `Document` lui-même -- un bon porte sa propre date,
    contrairement à un bloc de facture)."""
    resultat = (
        await session.execute(
            select(
                func.count().label("nb_bons_recus"),
                func.coalesce(func.sum(Document.total_ht), Decimal("0")).label(
                    "montant_bons_recus"
                ),
                func.count()
                .filter(Document.total_ht.is_(None))
                .label("nb_bons_sans_montant"),
            ).where(
                Document.type.in_(TYPES_BL),
                Document.statut == "recu",
                _condition_mois(mois),
            )
        )
    ).one()
    return (
        resultat.nb_bons_recus,
        resultat.montant_bons_recus,
        resultat.nb_bons_sans_montant,
    )


async def _dernier_mois_facture(session: AsyncSession) -> date | None:
    """1er du mois de la facture non archivée la plus récente -- même mois
    que le bilan (L5-D4) : `date_doc`, sinon la date de dépôt en heure de
    Paris. Voir docstring de module."""
    jour = (
        await session.execute(
            select(
                func.max(
                    func.coalesce(
                        Document.date_doc,
                        func.date(
                            func.timezone(str(FUSEAU_PARIS), Document.created_at)
                        ),
                    )
                )
            ).where(Document.type == "facture", Document.statut != "archive")
        )
    ).scalar_one_or_none()
    if jour is None:
        return None
    return date(jour.year, jour.month, 1)


async def tableau_de_bord(session: AsyncSession, *, mois: date) -> TableauDeBord:
    """Contenu complet du tableau de bord du mois -- voir docstring de
    module pour chaque règle de calcul."""
    mois = date(mois.year, mois.month, 1)
    lignes_bilan = await bilan_par_chantier(session, mois=mois, agence=None)

    def _somme(valeurs: list[Decimal]) -> Decimal:
        return sum(valeurs, Decimal("0"))

    totaux = TotauxMois(
        facture_ht=_somme([ligne.montants.facture_ht for ligne in lignes_bilan]),
        rapproche=_somme([ligne.montants.rapproche for ligne in lignes_bilan]),
        en_ecart=_somme([ligne.montants.en_ecart for ligne in lignes_bilan]),
        non_justifie=_somme([ligne.montants.non_justifie for ligne in lignes_bilan]),
        conforme=_somme([ligne.montants.conforme for ligne in lignes_bilan]),
    )

    nb_bl_factures, nb_bl_recus, nb_bl_manquants = await _compter_blocs(
        session, mois=mois
    )
    nb_bons_recus, montant_bons_recus, nb_bons_sans_montant = await _compter_bons_recus(
        session, mois=mois
    )

    anomalies_du_mois = await _anomalies_ouvertes_du_mois(session, mois=mois)
    nb_problemes_ouverts = len(anomalies_du_mois)
    nb_problemes_urgents = sum(
        1 for anomalie in anomalies_du_mois if anomalie.gravite == "haute"
    )

    anomalies_par_chantier: dict[uuid.UUID | None, list[AnomalieLue]] = {}
    for anomalie in anomalies_du_mois:
        anomalies_par_chantier.setdefault(anomalie.chantier_id, []).append(anomalie)

    chantiers = [
        ChantierTableau(
            chantier_id=ligne.chantier_id,
            nom_canonique=ligne.nom_canonique,
            client=ligne.client,
            agence=ligne.agence,
            etat=_etat_chantier(
                ligne, anomalies_par_chantier.get(ligne.chantier_id, [])
            ),
            montants=ligne.montants,
            a_verifier=ligne.montants.a_verifier,
        )
        for ligne in lignes_bilan
    ]
    chantiers.sort(key=_cle_tri_chantier)

    priorites = sorted(
        (
            ProblemePrioritaire(
                anomalie=anomalie, montant_en_jeu=_montant_en_jeu(anomalie)
            )
            for anomalie in anomalies_du_mois
        ),
        key=_cle_tri_priorite,
    )[:NB_PRIORITES_MAX]

    return TableauDeBord(
        mois=mois,
        totaux=totaux,
        nb_problemes_ouverts=nb_problemes_ouverts,
        nb_problemes_urgents=nb_problemes_urgents,
        nb_bl_factures=nb_bl_factures,
        nb_bl_recus=nb_bl_recus,
        nb_bl_manquants=nb_bl_manquants,
        chantiers=chantiers,
        priorites=priorites,
        dernier_mois_facture=await _dernier_mois_facture(session),
        nb_bons_recus=nb_bons_recus,
        montant_bons_recus=montant_bons_recus,
        nb_bons_sans_montant=nb_bons_sans_montant,
    )
