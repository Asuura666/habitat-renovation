"""Tableau de bord du mois (`ingest/tableau_de_bord.py`, refonte front T2) —
voir `docs/superpowers/specs/2026-09-23-refonte-front-design.md` §6.2 :
totaux du mois, problèmes ouverts/urgents, BL reçus/facturés, lignes
chantier enrichies d'un état calculé et les problèmes prioritaires. Aucun
calcul ni tri de ce genre ne doit être refait côté front (même principe que
`ingest/bilan.py`, L5-D1) : ce module ne fait qu'assembler des agrégats déjà
calculés par `ingest.bilan`/`ingest.anomalies`, jamais un second calcul
divergent.

`totaux` (L5-D3, `ingest.bilan.MontantsBilan`) : simple somme des montants
des lignes de `bilan_par_chantier(mois=mois, agence=None)` — les quatre
montants existants ne changent pas de définition ici. `conforme = max(
rapproche - en_ecart, 0)` est la seule grandeur nouvelle de cette tâche,
jamais négative (un chantier ne peut pas être "conforme" en négatif) :
décision du contrôleur, brief T2.

`nb_bl_factures`/`nb_bl_recus` : comptés directement sur la sous-requête
`_sous_requete_blocs`/`_conditions_base` d'`ingest.bilan` (mêmes conditions
de mois que le bilan, jamais une seconde définition de "quel bloc appartient
à ce mois").

Anomalies ouvertes du mois (correction de revue, fix round 1 -- décision du
contrôleur qui prime sur la règle de filtrage du brief, spec §6.2 "jamais un
second calcul divergent") : la portée exacte vient d'`ingest.bilan
._sous_requete_anomalies(mois)`, la même sous-requête que celle qui calcule
`MontantsBilan.nb_anomalies_ouvertes` par chantier (Ruling L5-R4) -- une
anomalie de bloc suit le mois de sa facture, une anomalie de document son
propre mois, une anomalie sans les deux `Anomalie.created_at`, les
documents archivés exclus. Ses identifiants sont ensuite relus par
`lister_anomalies(ids=..., limite=len(ids))` (voir `_anomalies_ouvertes_du_
mois` ci-dessous) pour obtenir leur forme `AnomalieLue` complète. L'ancienne
version filtrait après coup par `chantier_id` présent dans le bilan du mois
: un chantier qui facture ce mois-ci et portait par ailleurs une anomalie
ouverte d'un *autre* mois se voyait alors compter cette anomalie-là aussi
(fuite inter-mois, constat de revue) -- impossible avec la sous-requête du
bilan, qui borne déjà chaque anomalie à son propre mois. `nb_problemes_
ouverts`/`nb_problemes_urgents` et les `priorites` sont tous les trois
dérivés de cette même liste, jamais recalculés séparément ; `etat` en
dérive aussi (groupée par chantier), ce qui garantit qu'un chantier ne peut
jamais afficher `prix`/`quantites`/`a_voir` alors que
`montants.nb_anomalies_ouvertes == 0` (même portée que ce compteur,
Ruling L5-R4). Pas de plafond arbitraire (l'ancien `limite=500` tronquait
silencieusement) : `limite` vaut le nombre d'identifiants à relire, jamais
moins.

`etat` d'un chantier (brief T2, ordre de priorité strict) :
`chantier_id is None` -> `a_rattacher` ; `non_justifie > 0` -> `bl_manquant`
(un bloc non justifié prime sur toute anomalie de quantité/prix, CDC §5) ;
une anomalie ouverte du chantier en R07/R08/R09 -> `prix` ; en
R03/R04/R05/R17 -> `quantites` ; `nb_anomalies_ouvertes > 0` (déjà calculé
par `ingest.bilan`, Ruling L5-R4 : toutes les anomalies ouvertes du
chantier, pas seulement les quatre règles précédentes) -> `a_voir` ; sinon
`conforme`. Cet ordre place l'état `a_voir` du plan (§6, direction A) en
sixième valeur de `ETATS`, en plus des cinq états du document de conception
(`docs/superpowers/specs/2026-09-23-refonte-front-design.md` §6.2, qui n'en
liste que cinq) : le brief de cette tâche, plus précis et plus récent, fait
foi (écart signalé, pas une divergence silencieuse).

`montant_en_jeu` d'une priorité (brief T2) : lu directement sur
`AnomalieLue.detail` (jamais recalculé) — `R01`/`R02` portent
`detail["montant_ht"]`, `R05`/`R13` portent `detail["montant"]` (en valeur
absolue, une ligne négative sans origine peut porter un montant négatif),
toute autre règle ou toute valeur non convertible en `Decimal` renvoie
`None` plutôt que de lever.

Tri des `priorites` : gravité (haute, moyenne, basse) puis `montant_en_jeu`
décroissant (`None` en dernier) puis `cree_le` croissant (même convention
que `lister_anomalies`), les quatre premières.

Tri des `chantiers` : `a_verifier` (= `en_ecart + non_justifie`, brief T2)
décroissant puis `nom_canonique` croissant, le chantier non résolu
(`nom_canonique is None`) se départageant en dernier à montant égal — même
principe que le tri "dernière clé jamais ambiguë" d'`ingest.bilan`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.anomalies import AnomalieLue, lister_anomalies
from app.modules.ingest.bilan import (
    LigneBilanChantier,
    MontantsBilan,
    _conditions_base,
    _sous_requete_anomalies,
    _sous_requete_blocs,
    bilan_par_chantier,
)

ETATS = ("a_rattacher", "bl_manquant", "prix", "quantites", "a_voir", "conforme")

# Mêmes ensembles de règles que le brief T2 -- distincts de
# `ingest.bilan.REGLES_QUANTITE_OU_PRIX` (qui les mélange pour `en_ecart`) :
# ici il faut savoir lequel des deux états (`prix` ou `quantites`) afficher.
_REGLES_PRIX = frozenset({"R07", "R08", "R09"})
_REGLES_QUANTITES = frozenset({"R03", "R04", "R05", "R17"})

# Règles dont `detail` porte un montant chiffré exploitable pour trier les
# priorités (brief T2) -- deux clés différentes selon la règle.
_REGLES_MONTANT_HT = frozenset({"R01", "R02"})
_REGLES_MONTANT_ABSOLU = frozenset({"R05", "R13"})

_ORDRE_GRAVITE_PRIORITE: dict[str, int] = {"haute": 0, "moyenne": 1, "basse": 2}

NB_PRIORITES_MAX = 4


@dataclass(frozen=True)
class TotauxMois:
    """Les quatre montants du bilan du mois (L5-D3, somme sur tous les
    chantiers) plus `conforme` -- seule grandeur nouvelle de cette tâche,
    voir docstring de module."""

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
    etat: str
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
    chantiers: list[ChantierTableau]
    priorites: list[ProblemePrioritaire]


def _montant_en_jeu(anomalie: AnomalieLue) -> Decimal | None:
    """`detail["montant_ht"]` pour R01/R02, `abs(detail["montant"])` pour
    R05/R13, `None` pour toute autre règle ou toute valeur non convertible
    en `Decimal` (ex. le tiret cadratin `TIRET` des règles pures quand la
    valeur d'origine est absente) -- jamais une exception qui interromprait
    la construction du tableau de bord."""
    if anomalie.regle in _REGLES_MONTANT_HT:
        cle = "montant_ht"
    elif anomalie.regle in _REGLES_MONTANT_ABSOLU:
        cle = "montant"
    else:
        return None

    valeur = anomalie.detail.get(cle)
    if valeur is None:
        return None
    try:
        montant = Decimal(str(valeur))
    except InvalidOperation:
        return None
    return abs(montant) if anomalie.regle in _REGLES_MONTANT_ABSOLU else montant


def _cle_tri_priorite(
    probleme: ProblemePrioritaire,
) -> tuple[int, bool, Decimal, datetime]:
    """Gravité (haute, moyenne, basse) puis `montant_en_jeu` décroissant
    (`None` en dernier) puis `cree_le` croissant -- voir docstring de
    module."""
    montant = probleme.montant_en_jeu
    return (
        _ORDRE_GRAVITE_PRIORITE.get(
            probleme.anomalie.gravite, len(_ORDRE_GRAVITE_PRIORITE)
        ),
        montant is None,
        -montant if montant is not None else Decimal("0"),
        probleme.anomalie.cree_le,
    )


def _etat_chantier(
    ligne: LigneBilanChantier, anomalies_du_chantier: list[AnomalieLue]
) -> str:
    """Ordre de priorité strict du brief T2 -- voir docstring de module."""
    if ligne.chantier_id is None:
        return "a_rattacher"
    if ligne.montants.non_justifie > 0:
        return "bl_manquant"
    regles_ouvertes = {anomalie.regle for anomalie in anomalies_du_chantier}
    if regles_ouvertes & _REGLES_PRIX:
        return "prix"
    if regles_ouvertes & _REGLES_QUANTITES:
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


async def _compter_blocs(session: AsyncSession, *, mois: date) -> tuple[int, int]:
    """`nb_bl_factures`/`nb_bl_recus` -- même sous-requête de blocs que
    `ingest.bilan` (`_sous_requete_blocs`/`_conditions_base`), jamais une
    seconde définition du périmètre du mois."""
    blocs = _sous_requete_blocs(_conditions_base(mois))
    resultat = (
        await session.execute(
            select(
                func.count().label("nb_bl_factures"),
                func.count()
                .filter(blocs.c.statut_rapprochement == "recu")
                .label("nb_bl_recus"),
            ).select_from(blocs)
        )
    ).one()
    return resultat.nb_bl_factures, resultat.nb_bl_recus


async def tableau_de_bord(session: AsyncSession, *, mois: date) -> TableauDeBord:
    """Contenu complet du tableau de bord du mois -- voir docstring de
    module pour chaque règle de calcul."""
    lignes_bilan = await bilan_par_chantier(session, mois=mois, agence=None)

    facture_ht = sum(
        (ligne.montants.facture_ht for ligne in lignes_bilan), Decimal("0")
    )
    rapproche = sum((ligne.montants.rapproche for ligne in lignes_bilan), Decimal("0"))
    en_ecart = sum((ligne.montants.en_ecart for ligne in lignes_bilan), Decimal("0"))
    non_justifie = sum(
        (ligne.montants.non_justifie for ligne in lignes_bilan), Decimal("0")
    )
    totaux = TotauxMois(
        facture_ht=facture_ht,
        rapproche=rapproche,
        en_ecart=en_ecart,
        non_justifie=non_justifie,
        conforme=max(rapproche - en_ecart, Decimal("0")),
    )

    nb_bl_factures, nb_bl_recus = await _compter_blocs(session, mois=mois)

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
            a_verifier=ligne.montants.en_ecart + ligne.montants.non_justifie,
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
        chantiers=chantiers,
        priorites=priorites,
    )
