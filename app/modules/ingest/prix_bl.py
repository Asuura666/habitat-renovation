"""Contrôle des prix d'un bon (BL/enlèvement) face à la grille du
fournisseur et à la dernière facture retrouvée -- phase 3, tâche P7, spec
`docs/superpowers/specs/2026-09-27-prix-design.md` §6.

Orchestrateur (`ingest`) : construit les dataclasses pures de `rules.modeles`
(`LignePrixBl`, `ParametresPrixBl`) à partir de la base, appelle le moteur
pur (`rules.engine.evaluer_prix_bl`, R19-R25, tâche P6) puis délègue la
persistance des anomalies à `ingest.anomalies.synchroniser_anomalies` (même
mécanisme que `ingest.rapprochement.rapprocher_facture`).

- `controler_prix_bl` (spec §6.1) : contrôle un seul bon, ne commite jamais
  (l'appelant tient la transaction, comme `rapprocher_facture`).
- `controler_prix_bl_sans_echec` : encapsule l'appel précédent pour un
  déclenchement automatique (extraction, correction, changement de grille,
  spec §6.2) -- commite sa propre transaction et **ne fait jamais échouer
  l'appelant** : toute exception est journalisée (`_journaliser_echec`, même
  prudence que `ingest.rapprochement`) puis avalée, `None` en retour. C'est
  cette fonction que `ingest.extraction_bl`/`ingest.corrections` (fichiers
  partagés avec la session A) et `ingest.grilles.apres_changement_grille`
  appellent -- jamais `controler_prix_bl` directement.
- `recontroler_bons` (spec §6.2, §6.4) : recontrôle tous les bons non
  archivés (optionnellement restreints à un fournisseur et/ou datés à
  partir d'une date), chacun dans sa propre transaction -- réutilisée par
  `apres_changement_grille` (import/saisie d'un prix, spec §6.4) et par la
  commande CLI `controler-prix` (spec §6.2).

Tâche P8 (page « Prix à vérifier », spec §8) -- ajoutée à ce module plutôt
qu'à `ingest.grilles` : le recontrôle « bons portant une alerte de prix
ouverte sur le même produit » après une validation (spec §6.4) ne peut PAS
se limiter aux `anomalie_ids` transmis par le client -- le filtre de
période de la page Prix (`periode="jour"`, spec §8.1) peut restreindre le
groupe qu'elle affiche à une partie seulement des alertes ouvertes de ce
produit (un bon d'hier sur le même produit n'apparaît pas sous « Aujourd'hui »).
`valider_prix` reparcourt donc la base par `cle_produit`
(`_documents_prix_ouverts_meme_produit`, même requête que
`lister_alertes_prix` sans le filtre de période) pour recontrôler tous les
bons ouverts du produit, en plus de ceux des `anomalie_ids` reçus.
`ingest.grilles.apres_changement_grille` garde son paramètre
`cle_produit_modifiee` non câblé (import/saisie seuls l'appellent, jamais
avec ce paramètre) : lui n'a pas ce problème, il recontrôle déjà tous les
bons du fournisseur depuis `date_effet`.
- `lister_alertes_prix` (spec §8.1) : alertes ouvertes R19-R25 non
  masquées, regroupées par produit (clé de grille retrouvée si une règle de
  correspondance grille l'a posée, sinon clé calculée sur la ligne du bon,
  spec §4.1) -- une ligne d'un bon peut porter plusieurs alertes (ex.
  R19+R20), un même produit peut porter plusieurs bons. Triée par gravité,
  puis écart décroissant, puis date du bon décroissante.
- `valider_prix`/`contester_prix`/`ignorer_prix` (spec §8.2) : vérifient
  d'abord que `anomalie_ids` désigne des alertes toutes ouvertes, toutes de
  prix (R19-R25) et toutes du même groupe produit (`AlertesInvalides`, 409,
  sinon -- rien n'est modifié). `valider_prix` ajoute une ligne `grille_prix`
  (`source="validation"`), ferme les alertes du groupe au même prix que la
  ligne validée, puis recontrôle les bons du groupe (spec §6.4). Chaque
  alerte fermée écrit aussi l'entrée `anomalie_traitee`/`anomalie_ignoree`
  habituelle (même journal que `ingest.anomalies.traiter_anomalie`), en plus
  de l'entrée `prix_valide`/`prix_conteste`/`prix_ignore` propre à l'action.
- `recontroler_depuis_page` : bouton « Recontrôler les bons » (spec §8.2) --
  même règle de date par défaut que la commande CLI `controler-prix`
  (1ᵉʳ jour du mois précédent, dupliquée ici -- `ingest` ne peut pas
  importer `app.cli`).

Masquage (spec §6.5) : ce module ne masque rien lui-même -- il lit les
réglages `prix_…` (interrupteur général et les sept alertes) pour décider
*quoi calculer*, alors que `ingest.commun.regles_masquees`/`ingest.anomalies
.condition_regles_actives` décident *quoi montrer* à l'écran, aux comptes et
au bilan (point d'accroche distinct, déjà câblé par ce même tour de tâche).
Une alerte dont l'interrupteur est éteint n'est simplement pas évaluée ici
(comme R07/R08/R09, `rules.engine._evaluer_prix`) ; l'interrupteur général
éteint fait sortir tout de suite, sans rien recalculer ni supprimer (spec
§6.1, point 1)."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.anomalies import (
    COMMENTAIRE_LONGUEUR_MAX,
    COMMENTAIRE_LONGUEUR_MIN,
    synchroniser_anomalies,
)
from app.modules.ingest.commun import (
    CLE_ALERTE_PAR_REGLE,
    CLE_PRIX_CONTROLE_BL_ACTIF,
    regles_masquees,
)
from app.modules.ingest.commun import logger as _logger
from app.modules.ingest.grilles import PrixVigueur, prix_en_vigueur
from app.modules.ingest.models import (
    Anomalie,
    Article,
    Document,
    Fournisseur,
    GrillePrix,
    Journal,
    Ligne,
)
from app.modules.ingest.parametres import DEFINITIONS_PAR_CLE
from app.modules.ingest.referentiels import lire_parametre_decimal
from app.modules.normalize.prix import (
    ProduitGrille,
    cle_produit,
    normaliser_reference,
    ressemblance_produit,
    trouver_produit,
    unites_comparables,
)
from app.modules.normalize.prix import prix_net as _prix_net_grille
from app.modules.normalize.unites import normaliser_unite
from app.modules.rules.engine import REGLES_PRIX_BL, evaluer_prix_bl
from app.modules.rules.modeles import LignePrixBl, ParametresPrixBl, ReferencePrix

__all__ = [
    "AlerteProduit",
    "AlertesInvalides",
    "ResultatRecontrolePrix",
    "ValidationPrixEffectuee",
    "contester_prix",
    "controler_prix_bl",
    "controler_prix_bl_sans_echec",
    "ignorer_prix",
    "lister_alertes_prix",
    "recontroler_bons",
    "recontroler_depuis_page",
    "valider_prix",
]

# Types de document soumis au contrôle des prix (bons d'enlèvement Point.P
# traités comme des BL, CDC §4.5 -- même liste que `rapprochement._TYPES_BL`,
# dupliquée ici, module par module, comme le reste de la base de code).
_TYPES_BL: tuple[str, ...] = ("bl", "enlevement")

_CLES_SEUILS_PRIX_BL: tuple[str, ...] = (
    "prix_seuil_hausse_pct",
    "prix_seuil_baisse_pct",
    "prix_age_grille_mois",
    "prix_seuil_ressemblance_produit_pct",
)


def _journaliser_echec(etape: str, identifiant: uuid.UUID, exc: Exception) -> None:
    """Même prudence que `ingest.rapprochement._journaliser_echec` :
    jamais le contenu de l'exception, ni aucune valeur du bon."""
    _logger.error(
        "échec contrôle des prix (%s) pour %s : %s",
        etape,
        identifiant,
        type(exc).__name__,
    )


# --------------------------------------------------------------------------
# Réglages (spec §3.4, §6.1) : interrupteur général, seuils, sept alertes.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Reglages:
    controle_bl_actif: bool
    seuil_hausse_pct: Decimal
    seuil_baisse_pct: Decimal
    age_grille_mois: int
    seuil_ressemblance: int
    regles_actives: frozenset[str]


async def _parametre_bool(session: AsyncSession, cle: str, defaut: bool) -> bool:
    valeur = await lire_parametre_decimal(session, cle, Decimal("1" if defaut else "0"))
    return valeur != 0


async def _lire_reglages(session: AsyncSession) -> _Reglages:
    """Lit les douze réglages `prix_…` (spec §3.4), avec leurs valeurs par
    défaut reprises de `ingest.parametres.DEFINITIONS_PAR_CLE` (source
    unique, jamais recopiées en dur ici)."""
    controle_bl_actif = await _parametre_bool(
        session,
        CLE_PRIX_CONTROLE_BL_ACTIF,
        DEFINITIONS_PAR_CLE[CLE_PRIX_CONTROLE_BL_ACTIF].defaut != 0,
    )

    (
        cle_hausse,
        cle_baisse,
        cle_age_grille,
        cle_seuil_ressemblance,
    ) = _CLES_SEUILS_PRIX_BL
    seuil_hausse = await lire_parametre_decimal(
        session, cle_hausse, DEFINITIONS_PAR_CLE[cle_hausse].defaut
    )
    seuil_baisse = await lire_parametre_decimal(
        session, cle_baisse, DEFINITIONS_PAR_CLE[cle_baisse].defaut
    )
    age_grille = await lire_parametre_decimal(
        session, cle_age_grille, DEFINITIONS_PAR_CLE[cle_age_grille].defaut
    )
    seuil_ressemblance = await lire_parametre_decimal(
        session,
        cle_seuil_ressemblance,
        DEFINITIONS_PAR_CLE[cle_seuil_ressemblance].defaut,
    )

    actives: set[str] = set()
    for regle, cle in CLE_ALERTE_PAR_REGLE.items():
        defaut = DEFINITIONS_PAR_CLE[cle].defaut != 0
        if await _parametre_bool(session, cle, defaut):
            actives.add(regle)

    return _Reglages(
        controle_bl_actif=controle_bl_actif,
        seuil_hausse_pct=seuil_hausse,
        seuil_baisse_pct=seuil_baisse,
        age_grille_mois=int(age_grille),
        seuil_ressemblance=int(seuil_ressemblance),
        regles_actives=frozenset(actives),
    )


# --------------------------------------------------------------------------
# Lignes du bon soumises au contrôle, et articles résolus.
# --------------------------------------------------------------------------


async def _lignes_controlables(
    session: AsyncSession, document_id: uuid.UUID
) -> Sequence[Ligne]:
    """Lignes `article` du bon à `pu_ht > 0` (spec §6.1, point 3) : une
    ligne sans `pu_ht`, à prix nul ou négatif, ou de type `eco`/
    `commentaire` n'est jamais contrôlée."""
    resultat = await session.execute(
        select(Ligne)
        .where(
            Ligne.document_id == document_id,
            Ligne.type_ligne == "article",
            Ligne.pu_ht.is_not(None),
            Ligne.pu_ht > 0,
        )
        .order_by(Ligne.ordre)
    )
    return resultat.scalars().all()


async def _charger_articles(
    session: AsyncSession, article_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Article]:
    if not article_ids:
        return {}
    resultat = await session.execute(
        select(Article).where(Article.id.in_(tuple(article_ids)))
    )
    return {article.id: article for article in resultat.scalars().all()}


def _pu_ht(ligne: Ligne) -> Decimal:
    """`Ligne.pu_ht` est `Decimal | None` en base, mais `_lignes_controlables`
    ne renvoie que des lignes où il est strictement positif -- ce repli
    (jamais atteint en pratique) évite un `assert` défensif (interdit,
    CLAUDE.md/`ruff` S101) sur une colonne que le type ORM garde optionnelle."""
    return ligne.pu_ht if ligne.pu_ht is not None else Decimal("0")


# --------------------------------------------------------------------------
# Référence de grille (spec §4.1, §4.3, §4.4).
# --------------------------------------------------------------------------


def _reference_grille(
    ligne: Ligne,
    produits: Sequence[ProduitGrille],
    vigueur: Mapping[str, PrixVigueur],
    article: Article | None,
    seuil: int,
) -> tuple[ReferencePrix | None, tuple[str, ...]]:
    """`(reference, candidats)` -- `candidats` n'est renseigné que si aucune
    correspondance n'a pu être retenue faute de départage (spec §4.3,
    matière de R22)."""
    correspondance = trouver_produit(
        ligne.code_brut, ligne.article_brut, produits, seuil
    )
    if correspondance is None:
        return None, ()
    if correspondance.produit is None:
        return None, correspondance.candidats

    produit_grille = vigueur[correspondance.produit.cle]
    conversion = unites_comparables(
        ligne.unite_brut,
        produit_grille.unite,
        article.unite_cdt if article is not None else None,
        article.unite_fact if article is not None else None,
        article.ratio if article is not None else None,
        article.valide if article is not None else False,
    )
    prix = (
        produit_grille.prix_net * conversion.facteur
        if conversion.possible and conversion.facteur is not None
        else produit_grille.prix_net
    )
    return (
        ReferencePrix(
            prix=prix,
            unite=produit_grille.unite,
            date=produit_grille.date_effet,
            comparable=conversion.possible,
            methode=correspondance.methode,
            ressemblance=correspondance.ressemblance,
            designation=produit_grille.designation,
            source="grille",
            grille_posterieure_au_bon=produit_grille.posterieure,
        ),
        (),
    )


# --------------------------------------------------------------------------
# Dernier prix facturé (spec §6.3).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _CandidatFacture:
    """Une ligne de facture du fournisseur, candidate au « dernier prix
    facturé » d'une ligne du bon (spec §6.3)."""

    ligne: Ligne
    numero_facture: str | None
    date_doc: date
    unite_fact: str | None


async def _candidats_facture_bruts(
    session: AsyncSession, fournisseur_id: uuid.UUID, jusqu_a: date
) -> tuple[_CandidatFacture, ...]:
    """Requête effective de `_candidats_facture` : lignes `article` à
    `pu_ht > 0` des factures du fournisseur datées au plus tard `jusqu_a`."""
    resultat = await session.execute(
        select(Ligne, Document.numero, Document.date_doc, Article.unite_fact)
        .join(Document, Document.id == Ligne.document_id)
        .outerjoin(Article, Article.id == Ligne.article_id)
        .where(
            Document.type == "facture",
            Document.fournisseur_id == fournisseur_id,
            Document.date_doc.is_not(None),
            Document.date_doc <= jusqu_a,
            Ligne.type_ligne == "article",
            Ligne.pu_ht.is_not(None),
            Ligne.pu_ht > 0,
        )
    )
    return tuple(
        _CandidatFacture(
            ligne=ligne,
            numero_facture=numero,
            date_doc=date_doc if date_doc is not None else date.min,
            unite_fact=unite_fact,
        )
        for ligne, numero, date_doc, unite_fact in resultat.all()
    )


async def _candidats_facture(
    session: AsyncSession,
    fournisseur_id: uuid.UUID,
    jusqu_a: date,
    *,
    precalcules: Mapping[uuid.UUID, tuple[_CandidatFacture, ...]] | None = None,
) -> tuple[_CandidatFacture, ...]:
    """Lignes `article` à `pu_ht > 0` des factures du fournisseur datées au
    plus tard le `jusqu_a` (date du bon, spec §6.3).

    Sans `precalcules` : une requête par appel (cas normal, un seul bon --
    `controler_prix_bl` isolé). Avec `precalcules` (`recontroler_bons`, qui
    recontrôle potentiellement des centaines de bons d'un même fournisseur
    habituel) : filtre en mémoire l'ensemble déjà rapatrié une seule fois
    pour ce fournisseur (borné à la date la plus tardive utile du lot),
    plutôt que de requêter et retraiter les mêmes lignes de facture pour
    chaque bon (N+1)."""
    if precalcules is not None:
        candidats = precalcules.get(fournisseur_id, ())
        return tuple(c for c in candidats if c.date_doc <= jusqu_a)
    return await _candidats_facture_bruts(session, fournisseur_id, jusqu_a)


def _prix_net_facture(pu_ht: Decimal, remise_pct: Decimal | None) -> Decimal:
    """Prix net d'une ligne de facture (spec §6.3 : « prix net = pu_ht x
    (1 - remise_pct/100) si remise ») -- réutilise `normalize.prix.prix_net`,
    mais ne lève jamais : une remise hors bornes sur une vieille ligne de
    facture (donnée réelle, jamais validée par ce contrôle) retombe sur le
    prix brut plutôt que de faire échouer tout le contrôle du bon."""
    try:
        return _prix_net_grille(pu_ht, remise_pct)
    except ValueError:
        return pu_ht


def _reference_facture(
    ligne: Ligne,
    candidats: Sequence[_CandidatFacture],
    seuil: int,
    article: Article | None,
) -> ReferencePrix | None:
    """Le dernier prix facturé comparable à `ligne` (spec §6.3) : produit
    retrouvé par code, sinon par `ressemblance_produit >= seuil` (pas de
    départage d'unicité ici, à la différence de `trouver_produit` --
    spec §6.3 ne le demande pas) ; parmi les candidats retenus, le plus
    récent (`date_doc` puis `Ligne.created_at`)."""
    if not candidats:
        return None

    ref_bon = normaliser_reference(ligne.code_brut)
    par_code = (
        [c for c in candidats if normaliser_reference(c.ligne.code_brut) == ref_bon]
        if ref_bon
        else []
    )
    if par_code:
        meilleure = max(par_code, key=lambda c: (c.date_doc, c.ligne.created_at))
        methode = "reference"
        ressemblance = 100
    else:
        eligibles = [
            (c, ressemblance_produit(ligne.article_brut, c.ligne.article_brut))
            for c in candidats
        ]
        eligibles = [(c, score) for c, score in eligibles if score >= seuil]
        if not eligibles:
            return None
        meilleure, ressemblance = max(
            eligibles, key=lambda item: (item[0].date_doc, item[0].ligne.created_at)
        )
        methode = "nom"

    unite_facture = meilleure.unite_fact or meilleure.ligne.unite_brut
    conversion = unites_comparables(
        ligne.unite_brut,
        unite_facture,
        article.unite_cdt if article is not None else None,
        article.unite_fact if article is not None else None,
        article.ratio if article is not None else None,
        article.valide if article is not None else False,
    )
    prix_facture = _prix_net_facture(
        _pu_ht(meilleure.ligne), meilleure.ligne.remise_pct
    )
    prix = (
        prix_facture * conversion.facteur
        if conversion.possible and conversion.facteur is not None
        else prix_facture
    )
    return ReferencePrix(
        prix=prix,
        unite=unite_facture,
        date=meilleure.date_doc,
        comparable=conversion.possible,
        methode=methode,
        ressemblance=ressemblance,
        designation=meilleure.ligne.article_brut or "",
        source="facture",
        numero_facture=meilleure.numero_facture,
    )


# --------------------------------------------------------------------------
# controler_prix_bl (spec §6.1)
# --------------------------------------------------------------------------


async def _compter_alertes_ouvertes(
    session: AsyncSession, document_id: uuid.UUID
) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Anomalie)
            .where(
                Anomalie.document_id == document_id,
                Anomalie.regle.in_(tuple(REGLES_PRIX_BL)),
                Anomalie.statut == "ouverte",
            )
        )
    ).scalar_one()


async def controler_prix_bl(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    candidats_facture_precalcules: Mapping[uuid.UUID, tuple[_CandidatFacture, ...]]
    | None = None,
) -> int:
    """Contrôle les prix d'un bon face à la grille de son fournisseur et à
    la dernière facture retrouvée (spec §6.1) : renvoie le nombre d'alertes
    de prix ouvertes du bon après contrôle. Ne commite jamais (l'appelant
    tient la transaction, comme `rapprocher_facture`).

    `candidats_facture_precalcules` (usage interne, `recontroler_bons`) :
    voir `_candidats_facture`, évite de requêter les mêmes lignes de
    facture pour chaque bon d'un recontrôle massif du même fournisseur.

    Si `prix_controle_bl_actif` vaut 0, ou si le document n'est pas un bon
    (BL/enlèvement) non archivé avec un fournisseur résolu : ne fait rien
    (aucune synchronisation), renvoie simplement le nombre d'alertes déjà
    ouvertes (inchangé -- elles ne sont ni recalculées ni supprimées, spec
    §6.1 point 1 et §6.5)."""
    reglages = await _lire_reglages(session)
    if not reglages.controle_bl_actif:
        return await _compter_alertes_ouvertes(session, document_id)

    document = await session.get(Document, document_id)
    if (
        document is None
        or document.type not in _TYPES_BL
        or document.statut == "archive"
        or document.fournisseur_id is None
    ):
        return await _compter_alertes_ouvertes(session, document_id)

    date_bon = (
        document.date_doc
        if document.date_doc is not None
        else document.created_at.astimezone(FUSEAU_PARIS).date()
    )

    lignes = await _lignes_controlables(session, document_id)
    if not lignes:
        return await synchroniser_anomalies(
            session,
            anomalies=(),
            portee_document_id=document_id,
            portee_regles=tuple(REGLES_PRIX_BL),
        )

    vigueur = await prix_en_vigueur(session, document.fournisseur_id, date_bon)
    produits = tuple(
        ProduitGrille(
            cle=produit.cle_produit,
            reference=produit.reference,
            designation=produit.designation,
            unite=produit.unite,
            prix_net=produit.prix_net,
            date_effet=produit.date_effet,
        )
        for produit in vigueur.values()
    )

    article_ids = {ligne.article_id for ligne in lignes if ligne.article_id is not None}
    articles = await _charger_articles(session, article_ids)
    candidats_facture = await _candidats_facture(
        session,
        document.fournisseur_id,
        date_bon,
        precalcules=candidats_facture_precalcules,
    )

    lignes_prix_bl: list[LignePrixBl] = []
    for ligne in lignes:
        article = (
            articles.get(ligne.article_id) if ligne.article_id is not None else None
        )
        grille_ref, candidats = _reference_grille(
            ligne, produits, vigueur, article, reglages.seuil_ressemblance
        )
        dernier_ref = _reference_facture(
            ligne, candidats_facture, reglages.seuil_ressemblance, article
        )
        lignes_prix_bl.append(
            LignePrixBl(
                document_id=document_id,
                ligne_id=ligne.id,
                designation=ligne.article_brut or "",
                code=ligne.code_brut,
                prix_bon=_pu_ht(ligne),
                unite_bon=ligne.unite_brut,
                date_bon=date_bon,
                grille=grille_ref,
                candidats=candidats,
                dernier_prix=dernier_ref,
            )
        )

    parametres = ParametresPrixBl(
        seuil_hausse_pct=reglages.seuil_hausse_pct,
        seuil_baisse_pct=reglages.seuil_baisse_pct,
        age_grille_mois=reglages.age_grille_mois,
        aujourdhui=datetime.now(FUSEAU_PARIS).date(),
    )
    anomalies = evaluer_prix_bl(
        lignes_prix_bl, parametres, regles_actives=reglages.regles_actives
    )
    return await synchroniser_anomalies(
        session,
        anomalies=anomalies,
        portee_document_id=document_id,
        portee_regles=tuple(REGLES_PRIX_BL),
    )


async def controler_prix_bl_sans_echec(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    candidats_facture_precalcules: Mapping[uuid.UUID, tuple[_CandidatFacture, ...]]
    | None = None,
) -> int | None:
    """Encapsule `controler_prix_bl` pour un déclenchement automatique
    (extraction, correction, changement de grille -- spec §6.2) : commite sa
    propre transaction et ne fait **jamais** échouer l'action appelante --
    toute exception est journalisée (`_journaliser_echec`) puis avalée,
    `None` en retour (même idiome que `ingest.rapprochement
    .rapprocher_facture_sans_echec`). `candidats_facture_precalcules` : voir
    `controler_prix_bl` (usage interne, `recontroler_bons`)."""
    try:
        nb_ouvertes = await controler_prix_bl(
            session,
            document_id,
            candidats_facture_precalcules=candidats_facture_precalcules,
        )
        await session.commit()
        return nb_ouvertes
    except Exception as exc:
        await session.rollback()
        _journaliser_echec("controle_prix_bl", document_id, exc)
        return None


# --------------------------------------------------------------------------
# Recontrôles (spec §6.2, §6.4).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultatRecontrolePrix:
    """Issue de `recontroler_bons` : compteurs pour le bouton
    « Recontrôler les bons » (page Prix, tâche P8) et la commande CLI
    `controler-prix`."""

    nb_bons: int
    nb_echecs: int
    nb_alertes_ouvertes: int


def _debut_journee_paris(jour: date) -> datetime:
    return datetime.combine(jour, time.min, tzinfo=FUSEAU_PARIS)


async def recontroler_bons(
    session: AsyncSession,
    *,
    fournisseur_id: uuid.UUID | None = None,
    depuis: date | None = None,
) -> ResultatRecontrolePrix:
    """Recontrôle chaque bon (BL/enlèvement) non archivé, restreint à
    `fournisseur_id` si fourni (import/saisie d'un prix, spec §6.4) et daté
    à partir de `depuis` si fourni (sur `date_doc`, ou sur la date de dépôt
    -- heure de Paris -- si `date_doc` est absent). Chaque bon dans sa
    propre transaction (`controler_prix_bl_sans_echec`), un échec n'annule
    ni les autres bons ni l'appelant (spec §6.4 : « un échec est journalisé
    ... et n'annule pas le changement de grille »)."""
    conditions: list[Any] = [Document.type.in_(_TYPES_BL), Document.statut != "archive"]
    if fournisseur_id is not None:
        conditions.append(Document.fournisseur_id == fournisseur_id)
    if depuis is not None:
        conditions.append(
            or_(
                Document.date_doc >= depuis,
                and_(
                    Document.date_doc.is_(None),
                    Document.created_at >= _debut_journee_paris(depuis),
                ),
            )
        )

    resultat_documents = await session.execute(
        select(
            Document.id, Document.fournisseur_id, Document.date_doc, Document.created_at
        ).where(*conditions)
    )
    documents = resultat_documents.all()
    ids = tuple(d.id for d in documents)

    # Une seule requête de lignes de facture par fournisseur du lot (au lieu
    # d'une par bon, spec §6.4 -- un recontrôle massif porte souvent sur des
    # centaines de bons d'un même fournisseur habituel) : bornée à la date
    # la plus tardive utile de ce fournisseur dans le lot, puis filtrée en
    # mémoire par bon dans `_candidats_facture` (voir sa docstring).
    dates_par_fournisseur: dict[uuid.UUID, date] = {}
    for doc in documents:
        if doc.fournisseur_id is None:
            continue
        date_bon = (
            doc.date_doc
            if doc.date_doc is not None
            else doc.created_at.astimezone(FUSEAU_PARIS).date()
        )
        actuelle = dates_par_fournisseur.get(doc.fournisseur_id)
        if actuelle is None or date_bon > actuelle:
            dates_par_fournisseur[doc.fournisseur_id] = date_bon

    candidats_facture_par_fournisseur = {
        fid: await _candidats_facture_bruts(session, fid, date_max)
        for fid, date_max in dates_par_fournisseur.items()
    }

    nb_echecs = 0
    total_ouvertes = 0
    for document_id in ids:
        resultat = await controler_prix_bl_sans_echec(
            session,
            document_id,
            candidats_facture_precalcules=candidats_facture_par_fournisseur,
        )
        if resultat is None:
            nb_echecs += 1
        else:
            total_ouvertes += resultat

    return ResultatRecontrolePrix(
        nb_bons=len(ids), nb_echecs=nb_echecs, nb_alertes_ouvertes=total_ouvertes
    )


# --------------------------------------------------------------------------
# Page « Prix à vérifier » (spec §8, tâche P8).
# --------------------------------------------------------------------------

# Tiret cadratin -- même convention que `rules.rules._prix_bl.TIRET` pour une
# valeur de `detail` absente ; dupliqué ici (module pur non importable en
# pratique commode depuis `ingest`, même principe que `_prix_net_facture`
# ci-dessus qui duplique déjà l'idiome plutôt que d'importer un module privé
# de `rules.rules`).
_TIRET = "—"

# Règles qui posent une correspondance de grille (spec §5.2) : seules
# celles-là peuvent porter `designation_grille` dans leur `detail`, socle du
# regroupement par produit (spec §8.1, §4.1).
_REGLES_GRILLE: frozenset[str] = frozenset({"R19", "R21", "R23", "R25"})

# Règles qui portent un écart chiffré (`ecart_pct`) dans leur `detail` --
# R22 (absent de la grille), R23 (reconnu par le nom) et R24/R25 n'en
# portent pas (spec §5.2).
_REGLES_ECART: frozenset[str] = frozenset({"R19", "R20", "R21"})

_GRAVITE_RANG: dict[str, int] = {"haute": 0, "moyenne": 1, "basse": 2}


def _premier_jour_mois_precedent(aujourdhui: date) -> date:
    """Dupliqué depuis `app.cli._premier_jour_mois_precedent` (`ingest` ne
    peut pas importer `app.cli`, sens interdit de dépendance) : borne par
    défaut du recontrôle « Recontrôler les bons » (spec §6.2), identique à
    celle de la commande CLI `controler-prix`."""
    if aujourdhui.month == 1:
        return date(aujourdhui.year - 1, 12, 1)
    return date(aujourdhui.year, aujourdhui.month - 1, 1)


def _formater_montant(montant: Decimal) -> str:
    """Dupliqué depuis `ingest.export._formater_montant` (deux décimales,
    virgule française, arrondi comptable `ROUND_HALF_UP`) : matière du
    commentaire automatique de `valider_prix` (spec §8.2, « Prix validé :
    12,34 € (grille mise à jour) »)."""
    arrondi = montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{arrondi:.2f}".replace(".", ",")


def _decimal_ou_aucun(brut: Any) -> Decimal | None:
    """Une valeur de `detail` (toujours une chaîne, moteur de règles pur) en
    `Decimal`, ou `None` si absente/illisible (même prudence que
    `ingest.tableau_de_bord._montant_en_jeu` : le tiret cadratin `TIRET` des
    valeurs manquantes n'est jamais converti)."""
    if brut is None:
        return None
    try:
        return Decimal(str(brut))
    except InvalidOperation:
        return None


def _entier_ou_aucun(brut: Any) -> int | None:
    valeur = _decimal_ou_aucun(brut)
    return int(valeur) if valeur is not None else None


def _date_ou_aucune(brut: Any) -> date | None:
    if not isinstance(brut, str):
        return None
    try:
        return date.fromisoformat(brut)
    except ValueError:
        return None


def _texte_ou_aucun(brut: Any) -> str | None:
    if brut is None or brut == _TIRET:
        return None
    return str(brut)


@dataclass(frozen=True)
class _LigneAlerte:
    """Une ligne de bon portant au moins une alerte de prix ouverte, avec
    toutes ses anomalies (potentiellement plusieurs règles sur la même
    ligne, ex. R19+R20) -- aide interne à `lister_alertes_prix` et à la
    vérification du groupe des actions (`_charger_groupe`)."""

    ligne: Ligne
    document: Document
    fournisseur_nom: str
    anomalies: tuple[Anomalie, ...]


def cle_produit_alerte(ligne: Ligne, anomalies: Sequence[Anomalie]) -> str:
    """Clé de regroupement d'une ligne en alerte par produit (spec §8.1) :
    celle du produit de grille retrouvé, si une des anomalies de cette
    ligne porte `designation_grille` (règles de grille, spec §5.2) --
    combinée à `code` seulement quand la correspondance a été faite par
    référence (seul cas où `code` coïncide avec la référence du produit de
    grille, spec §4.3) ; sinon la clé calculée sur la ligne du bon elle-même
    (spec §4.1, même calcul qu'`ingest.grilles` pour une ligne de grille).

    R25 seule (sans R19/R21/R23) ne porte pas `designation_grille` -- mais
    elle n'est possible que lorsque le produit a été retrouvé par référence
    (R23 se déclenche sans condition de seuil dès qu'un produit est retrouvé
    par le nom, spec §5.2) : le repli sur la ligne du bon calcule alors la
    même clé `ref:...` que le produit de grille, sans perte.

    Publique (spec 2026-10-01 §4.1) : aussi la clé d'une contestation,
    relue par `ingest.contestations_prix`."""
    for anomalie in anomalies:
        if anomalie.regle in _REGLES_GRILLE:
            designation_grille = anomalie.detail.get("designation_grille")
            if designation_grille:
                methode = anomalie.detail.get("methode")
                code = anomalie.detail.get("code")
                reference = code if methode == "reference" and code != _TIRET else None
                return cle_produit(reference, str(designation_grille))
    return cle_produit(ligne.code_brut, ligne.article_brut)


def _cle_groupe(ligne_alerte: _LigneAlerte) -> str:
    """Clé de regroupement d'une ligne en alerte par produit (spec §8.1) :
    voir `cle_produit_alerte`."""
    return cle_produit_alerte(ligne_alerte.ligne, ligne_alerte.anomalies)


def _fournisseur_id_document(document: Document) -> uuid.UUID:
    """`Document.fournisseur_id` est `UUID | None` en base, mais toute ligne
    lue par `lister_alertes_prix`/`_charger_groupe` vient d'une jointure
    (interne, ou déjà vérifiée par `controler_prix_bl` qui n'écrit jamais
    d'anomalie de prix sur un document sans fournisseur) : ce repli (jamais
    atteint en pratique) évite un `assert` défensif (interdit, CLAUDE.md/
    `ruff` S101) sur une colonne que le type ORM garde optionnelle -- même
    principe que `_pu_ht` ci-dessus."""
    return (
        document.fournisseur_id
        if document.fournisseur_id is not None
        else uuid.UUID(int=0)
    )


@dataclass(frozen=True)
class AlerteProduit:
    """Une rangée de la page « Prix à vérifier » (spec §8.1) -- un produit,
    regroupant toutes les alertes ouvertes de tous ses bons. Les champs
    « grille »/« dernier prix » viennent du bon le plus récent du groupe
    (`date_bon`, puis `Document.created_at`) ; `nb_bons`/
    `nb_prix_differents` comptent sur l'ensemble du groupe.

    `unite_grille_non_comparable` distingue « produit absent de la grille »
    (R22, `prix_grille` restera `None`) de « grille présente mais unité non
    comparable » (R24 : un produit de la grille existe mais son prix n'a pas
    pu être comparé -- `rules/R24.py`) -- ce second cas n'a ni `prix_grille`
    ni R22 et ne doit pas être affiché comme « absent de la grille » (constat
    front, tour 2)."""

    fournisseur_id: uuid.UUID
    fournisseur: str
    produit: str
    code: str | None
    prix_bon: Decimal
    unite_bon: str | None
    date_bon: date
    nb_bons: int
    nb_prix_differents: int
    prix_grille: Decimal | None
    unite_grille: str | None
    date_grille: date | None
    grille_posterieure_au_bon: bool
    dernier_prix: Decimal | None
    unite_dernier_prix: str | None
    date_dernier_prix: date | None
    numero_facture: str | None
    ecart_pct: Decimal | None
    methode: str | None
    ressemblance: int | None
    unite_grille_non_comparable: str | None
    regles: tuple[str, ...]
    anomalie_ids: tuple[uuid.UUID, ...]
    document_id: uuid.UUID
    ligne_id: uuid.UUID
    numero_interne: int | None


def _date_bon_ligne(ligne_alerte: _LigneAlerte) -> date:
    document = ligne_alerte.document
    if document.date_doc is not None:
        return document.date_doc
    return document.created_at.astimezone(FUSEAU_PARIS).date()


def _cle_tri_recent(ligne_alerte: _LigneAlerte) -> tuple[date, datetime]:
    return (_date_bon_ligne(ligne_alerte), ligne_alerte.document.created_at)


def _trouver_anomalie(
    items_du_plus_recent: Sequence[_LigneAlerte], regles: frozenset[str]
) -> Anomalie | None:
    """La première anomalie de l'une de `regles`, en parcourant les lignes
    du groupe du plus récent bon au plus ancien (spec §8.1 : les champs
    affichés viennent du bon le plus récent, à défaut de celui qui en porte
    encore la trace)."""
    for item in items_du_plus_recent:
        for anomalie in item.anomalies:
            if anomalie.regle in regles:
                return anomalie
    return None


def _plus_grand_ecart(anomalies: Sequence[Anomalie]) -> Decimal | None:
    """Le plus grand des écarts (en valeur absolue, signe conservé) parmi
    les anomalies de `_REGLES_ECART` -- spec §8.1 : « le plus grand des deux
    écarts calculés, avec sa flèche »."""
    valeurs = [
        valeur
        for anomalie in anomalies
        if anomalie.regle in _REGLES_ECART
        for valeur in (_decimal_ou_aucun(anomalie.detail.get("ecart_pct")),)
        if valeur is not None
    ]
    if not valeurs:
        return None
    return max(valeurs, key=abs)


def _gravite_rang(items: Sequence[_LigneAlerte]) -> int:
    return min(
        _GRAVITE_RANG.get(anomalie.gravite, 3)
        for item in items
        for anomalie in item.anomalies
    )


def _alerte_produit(items: Sequence[_LigneAlerte]) -> AlerteProduit:
    items_tries = sorted(items, key=_cle_tri_recent, reverse=True)
    plus_recent = items_tries[0]

    toutes_anomalies = tuple(a for item in items for a in item.anomalies)
    regles = tuple(sorted({a.regle for a in toutes_anomalies}))
    # Ordre déterministe : d'abord les anomalies de la ligne la plus récente
    # (celle dont viennent les champs affichés ; le front en garde la
    # première), triées par règle puis identifiant, puis celles des autres.
    anomalie_ids = tuple(
        a.id
        for item in items_tries
        for a in sorted(item.anomalies, key=lambda x: (x.regle, x.id))
    )

    document_ids = {item.document.id for item in items}
    prix_distincts = {
        item.ligne.pu_ht for item in items if item.ligne.pu_ht is not None
    }

    grille_anomalie = _trouver_anomalie(items_tries, _REGLES_GRILLE)
    dernier_prix_anomalie = _trouver_anomalie(items_tries, frozenset({"R20"}))

    prix_grille = unite_grille = date_grille = None
    methode = ressemblance = None
    grille_posterieure_au_bon = False
    if grille_anomalie is not None:
        detail = grille_anomalie.detail
        prix_grille = _decimal_ou_aucun(detail.get("prix_grille"))
        unite_grille = _texte_ou_aucun(detail.get("unite_grille"))
        date_grille = _date_ou_aucune(detail.get("date_grille"))
        methode = detail.get("methode")
        ressemblance = _entier_ou_aucun(detail.get("ressemblance"))
        grille_posterieure_au_bon = detail.get("grille_posterieure_au_bon") == "oui"

    dernier_prix = unite_dernier_prix = date_dernier_prix = numero_facture = None
    if dernier_prix_anomalie is not None:
        detail = dernier_prix_anomalie.detail
        dernier_prix = _decimal_ou_aucun(detail.get("dernier_prix"))
        unite_dernier_prix = _texte_ou_aucun(detail.get("unite_dernier_prix"))
        date_dernier_prix = _date_ou_aucune(detail.get("date_dernier_prix"))
        numero_facture = _texte_ou_aucun(detail.get("numero_facture"))
        if methode is None:
            methode = detail.get("methode")
        if ressemblance is None:
            ressemblance = _entier_ou_aucun(detail.get("ressemblance"))

    unite_grille_non_comparable = None
    r24_anomalie = _trouver_anomalie(items_tries, frozenset({"R24"}))
    if r24_anomalie is not None:
        unite_grille_non_comparable = _texte_ou_aucun(
            r24_anomalie.detail.get("unite_grille")
        )

    return AlerteProduit(
        fournisseur_id=_fournisseur_id_document(plus_recent.document),
        fournisseur=plus_recent.fournisseur_nom,
        produit=plus_recent.ligne.article_brut or "",
        code=plus_recent.ligne.code_brut,
        prix_bon=_pu_ht(plus_recent.ligne),
        unite_bon=plus_recent.ligne.unite_brut,
        date_bon=_date_bon_ligne(plus_recent),
        nb_bons=len(document_ids),
        nb_prix_differents=len(prix_distincts),
        prix_grille=prix_grille,
        unite_grille=unite_grille,
        date_grille=date_grille,
        grille_posterieure_au_bon=grille_posterieure_au_bon,
        dernier_prix=dernier_prix,
        unite_dernier_prix=unite_dernier_prix,
        date_dernier_prix=date_dernier_prix,
        numero_facture=numero_facture,
        ecart_pct=_plus_grand_ecart(plus_recent.anomalies),
        methode=methode,
        ressemblance=ressemblance,
        unite_grille_non_comparable=unite_grille_non_comparable,
        regles=regles,
        anomalie_ids=anomalie_ids,
        document_id=plus_recent.document.id,
        ligne_id=plus_recent.ligne.id,
        numero_interne=plus_recent.document.numero_interne,
    )


def _cle_tri_produit(items: Sequence[_LigneAlerte], produit: AlerteProduit) -> Any:
    """Tri de la page Prix (spec §8.1) : gravité haute d'abord, puis écart
    décroissant (en valeur absolue -- une alerte sans écart chiffré, ex.
    R22/R23/R24/R25 seules, est classée après celles qui en ont un), puis
    date du bon décroissante."""
    ecart_abs = abs(produit.ecart_pct) if produit.ecart_pct is not None else Decimal(-1)
    return (_gravite_rang(items), -ecart_abs, -produit.date_bon.toordinal())


async def lister_alertes_prix(
    session: AsyncSession,
    *,
    periode: str = "tout",
    fournisseur_id: uuid.UUID | None = None,
) -> tuple[AlerteProduit, ...]:
    """Alertes de prix ouvertes et non masquées (spec §8.1), regroupées par
    produit (`_cle_groupe`). `periode="jour"` : anomalies créées aujourd'hui
    (heure de Paris) seulement -- `"tout"` (défaut) ne filtre pas."""
    exclues = await regles_masquees(session)
    conditions: list[Any] = [
        Anomalie.regle.in_(tuple(REGLES_PRIX_BL)),
        Anomalie.statut == "ouverte",
    ]
    if exclues:
        conditions.append(Anomalie.regle.not_in(tuple(exclues)))
    if periode == "jour":
        aujourdhui = datetime.now(FUSEAU_PARIS).date()
        conditions.append(Anomalie.created_at >= _debut_journee_paris(aujourdhui))
        conditions.append(
            Anomalie.created_at < _debut_journee_paris(aujourdhui + timedelta(days=1))
        )
    if fournisseur_id is not None:
        conditions.append(Document.fournisseur_id == fournisseur_id)

    resultat = await session.execute(
        select(Anomalie, Ligne, Document, Fournisseur.nom)
        .join(Ligne, Ligne.id == Anomalie.ligne_id)
        .join(Document, Document.id == Anomalie.document_id)
        .join(Fournisseur, Fournisseur.id == Document.fournisseur_id)
        .where(*conditions)
    )

    par_ligne_anomalies: dict[uuid.UUID, list[Anomalie]] = {}
    par_ligne_contexte: dict[uuid.UUID, tuple[Ligne, Document, str]] = {}
    for anomalie, ligne, document, fournisseur_nom in resultat.all():
        par_ligne_anomalies.setdefault(ligne.id, []).append(anomalie)
        par_ligne_contexte.setdefault(ligne.id, (ligne, document, fournisseur_nom))

    groupes: dict[tuple[uuid.UUID, str], list[_LigneAlerte]] = {}
    for ligne_id, anomalies in par_ligne_anomalies.items():
        ligne, document, fournisseur_nom = par_ligne_contexte[ligne_id]
        ligne_alerte = _LigneAlerte(
            ligne=ligne,
            document=document,
            fournisseur_nom=fournisseur_nom,
            anomalies=tuple(anomalies),
        )
        cle = (_fournisseur_id_document(document), _cle_groupe(ligne_alerte))
        groupes.setdefault(cle, []).append(ligne_alerte)

    resultats = [(items, _alerte_produit(items)) for items in groupes.values()]
    resultats.sort(key=lambda paire: _cle_tri_produit(paire[0], paire[1]))
    return tuple(produit for _, produit in resultats)


# --------------------------------------------------------------------------
# Actions de la page Prix (spec §8.2).
# --------------------------------------------------------------------------


class AlertesInvalides(Exception):
    """`anomalie_ids` ne désigne pas des alertes toutes ouvertes, toutes de
    prix (R19-R25) et toutes du même groupe produit (spec §8.2 : 409, rien
    n'est modifié)."""


async def _charger_groupe(
    session: AsyncSession, anomalie_ids: Sequence[uuid.UUID]
) -> tuple[list[Anomalie], uuid.UUID, str]:
    """Charge les anomalies de `anomalie_ids` et vérifie qu'elles forment un
    groupe valide pour une action de la page Prix (spec §8.2) : non vide,
    toutes existantes, toutes `ouverte`, toutes de prix (R19-R25), toutes du
    même fournisseur et du même produit (`_cle_groupe`, agrégée par ligne du
    bon -- une ligne peut porter plusieurs des `anomalie_ids`, ex. R19+R20,
    et doit alors être regroupée une seule fois). `AlertesInvalides` sinon,
    avant toute modification. Renvoie les anomalies (peu importe l'ordre),
    le `fournisseur_id` du groupe et sa clé produit (`_cle_groupe`) -- cette
    dernière sert à `valider_prix` pour retrouver, au-delà des seules
    `anomalie_ids` transmises (qui peuvent être restreintes par le filtre de
    période de la page Prix, spec §8.1), tous les bons ouverts du même
    produit à recontrôler (spec §6.4)."""
    if not anomalie_ids:
        raise AlertesInvalides("aucune alerte sélectionnée")
    ids_uniques = tuple(dict.fromkeys(anomalie_ids))

    resultat = await session.execute(
        select(Anomalie, Ligne, Document)
        .join(Ligne, Ligne.id == Anomalie.ligne_id)
        .join(Document, Document.id == Anomalie.document_id)
        .where(Anomalie.id.in_(ids_uniques))
    )
    lignes = resultat.all()
    trouve_par_id = {
        anomalie.id: (anomalie, ligne, document) for anomalie, ligne, document in lignes
    }
    if len(trouve_par_id) != len(ids_uniques):
        raise AlertesInvalides("alerte introuvable")

    elements = [trouve_par_id[i] for i in ids_uniques]
    for anomalie, _ligne, _document in elements:
        if anomalie.statut != "ouverte" or anomalie.regle not in REGLES_PRIX_BL:
            raise AlertesInvalides(
                "alerte déjà réglée, ou hors du contrôle des prix des bons"
            )

    par_ligne_anomalies: dict[uuid.UUID, list[Anomalie]] = {}
    par_ligne_contexte: dict[uuid.UUID, tuple[Ligne, Document]] = {}
    for anomalie, ligne, document in elements:
        par_ligne_anomalies.setdefault(ligne.id, []).append(anomalie)
        par_ligne_contexte.setdefault(ligne.id, (ligne, document))

    cle_reference: tuple[uuid.UUID | None, str] | None = None
    for ligne_id, anomalies_ligne in par_ligne_anomalies.items():
        ligne, document = par_ligne_contexte[ligne_id]
        ligne_alerte = _LigneAlerte(
            ligne=ligne,
            document=document,
            fournisseur_nom="",
            anomalies=tuple(anomalies_ligne),
        )
        cle = (document.fournisseur_id, _cle_groupe(ligne_alerte))
        if cle_reference is None:
            cle_reference = cle
        elif cle != cle_reference:
            raise AlertesInvalides(
                "les alertes ne portent pas toutes sur le même produit"
            )

    if cle_reference is None:
        # Toujours faux en pratique (`elements` est non vide, la boucle
        # ci-dessus l'aura donc posé au moins une fois) -- défensif, jamais
        # un `assert` dans du code de production (S101).
        raise AlertesInvalides("fournisseur introuvable pour ce groupe")
    fournisseur_id = cle_reference[0]
    if fournisseur_id is None:
        # Toujours faux en pratique (un bon contrôlé a nécessairement un
        # fournisseur, `controler_prix_bl` l'exige) -- même prudence
        # défensive que ci-dessus.
        raise AlertesInvalides("fournisseur introuvable pour ce groupe")

    return (
        [anomalie for anomalie, _ligne, _document in elements],
        fournisseur_id,
        cle_reference[1],
    )


async def _documents_prix_ouverts_meme_produit(
    session: AsyncSession, *, fournisseur_id: uuid.UUID, cle_produit: str
) -> set[uuid.UUID]:
    """Tous les bons non archivés de `fournisseur_id` portant au moins une
    alerte de prix ouverte sur le produit `cle_produit` (spec §6.4 : « les
    bons portant une alerte de prix ouverte sur le même produit »),
    indépendamment du filtre de période de la page Prix -- au contraire des
    `anomalie_ids` transmis par le client à `valider_prix`, qui peuvent ne
    couvrir qu'une partie de ces bons (page filtrée sur « Aujourd'hui » par
    exemple, spec §8.1). Même requête de base que `lister_alertes_prix`,
    sans le filtre de période, restreinte au fournisseur et regroupée par
    produit comme `_charger_groupe`."""
    resultat = await session.execute(
        select(Anomalie, Ligne, Document)
        .join(Ligne, Ligne.id == Anomalie.ligne_id)
        .join(Document, Document.id == Anomalie.document_id)
        .where(
            Anomalie.regle.in_(tuple(REGLES_PRIX_BL)),
            Anomalie.statut == "ouverte",
            Document.fournisseur_id == fournisseur_id,
            Document.statut != "archive",
        )
    )
    par_ligne_anomalies: dict[uuid.UUID, list[Anomalie]] = {}
    par_ligne_contexte: dict[uuid.UUID, tuple[Ligne, Document]] = {}
    for anomalie, ligne, document in resultat.all():
        par_ligne_anomalies.setdefault(ligne.id, []).append(anomalie)
        par_ligne_contexte.setdefault(ligne.id, (ligne, document))

    documents: set[uuid.UUID] = set()
    for ligne_id, anomalies_ligne in par_ligne_anomalies.items():
        ligne, document = par_ligne_contexte[ligne_id]
        ligne_alerte = _LigneAlerte(
            ligne=ligne,
            document=document,
            fournisseur_nom="",
            anomalies=tuple(anomalies_ligne),
        )
        if _cle_groupe(ligne_alerte) == cle_produit:
            documents.add(document.id)
    return documents


def _avant_anomalie(anomalie: Anomalie) -> dict[str, str | None]:
    return {"statut": anomalie.statut, "commentaire": anomalie.commentaire}


def _fermer_anomalie(
    anomalie: Anomalie, *, statut: str, commentaire: str, auteur_id: uuid.UUID
) -> None:
    anomalie.statut = statut
    anomalie.commentaire = commentaire
    anomalie.traitee_par = auteur_id
    anomalie.traitee_le = datetime.now(UTC)


_ACTION_JOURNAL_PAR_STATUT: dict[str, str] = {
    "traitee": "anomalie_traitee",
    "ignoree": "anomalie_ignoree",
}


@dataclass(frozen=True)
class ValidationPrixEffectuee:
    """Résultat de `valider_prix` (spec §8.2)."""

    prix_net: Decimal
    date_effet: date
    nb_alertes_reglees: int


async def valider_prix(
    session: AsyncSession,
    *,
    anomalie_ids: Sequence[uuid.UUID],
    ligne_id: uuid.UUID,
    auteur_id: uuid.UUID,
) -> ValidationPrixEffectuee:
    """« Valider ce prix » (spec §8.2) : nouvelle ligne `grille_prix`
    (`source="validation"`) au prix (sans remise) et à l'unité de la ligne
    `ligne_id` (le bon le plus récent du groupe), date d'effet = date de ce
    bon ; référence/désignation/marque/famille reprennent le produit de
    grille retrouvé pour cette ligne s'il existe, sinon le code et la
    désignation du bon (spec §4.3, même correspondance que
    `controler_prix_bl`). Les alertes du groupe dont le prix du bon (brut,
    sans remise) est égal à ce prix sont réglées (`traitee`, commentaire
    automatique) ; les autres restent ouvertes, à recontrôler.

    Lève `AlertesInvalides` (voir `_charger_groupe`) ou si `ligne_id` n'est
    pas l'une des lignes des alertes fournies. Commite, puis recontrôle
    (spec §6.4) tous les bons non archivés portant une alerte de prix
    ouverte sur ce même produit -- pas seulement ceux des `anomalie_ids`
    reçus, qui peuvent être restreints par le filtre de période de la page
    Prix (`_documents_prix_ouverts_meme_produit`) -- une ligne dont le prix
    diffère peut sortir ou rester en alerte selon la nouvelle grille,
    réévaluée à ce moment-là."""
    anomalies, fournisseur_id, cle_produit_groupe = await _charger_groupe(
        session, anomalie_ids
    )

    lignes_du_groupe = {a.ligne_id for a in anomalies}
    if ligne_id not in lignes_du_groupe:
        raise AlertesInvalides(
            "la ligne indiquée ne correspond à aucune des alertes fournies"
        )

    ligne = await session.get(Ligne, ligne_id)
    if ligne is None or ligne.pu_ht is None or ligne.pu_ht <= 0:
        raise AlertesInvalides("cette ligne n'a plus de prix à valider")
    document = await session.get(Document, ligne.document_id)
    if document is None:
        raise AlertesInvalides("bon introuvable")

    date_bon = (
        document.date_doc
        if document.date_doc is not None
        else document.created_at.astimezone(FUSEAU_PARIS).date()
    )

    reglages = await _lire_reglages(session)
    vigueur = await prix_en_vigueur(session, fournisseur_id, date_bon)
    produits = tuple(
        ProduitGrille(
            cle=produit.cle_produit,
            reference=produit.reference,
            designation=produit.designation,
            unite=produit.unite,
            prix_net=produit.prix_net,
            date_effet=produit.date_effet,
        )
        for produit in vigueur.values()
    )
    correspondance = trouver_produit(
        ligne.code_brut, ligne.article_brut, produits, reglages.seuil_ressemblance
    )
    produit_vigueur = (
        vigueur.get(correspondance.produit.cle)
        if correspondance is not None and correspondance.produit is not None
        else None
    )

    if produit_vigueur is not None:
        reference = produit_vigueur.reference
        designation = produit_vigueur.designation
        marque = produit_vigueur.marque
        famille = produit_vigueur.famille
        cle = produit_vigueur.cle_produit
        ancien_prix_net: Decimal | None = produit_vigueur.prix_net
    else:
        reference = ligne.code_brut
        designation = ligne.article_brut or ""
        marque = None
        famille = None
        cle = cle_produit(ligne.code_brut, ligne.article_brut)
        ancien_prix_net = None

    unite_normalisee = normaliser_unite(ligne.unite_brut)
    unite_code = unite_normalisee.code if unite_normalisee is not None else None
    net = _prix_net_grille(ligne.pu_ht, None)

    nouvelle_ligne = GrillePrix(
        fournisseur_id=fournisseur_id,
        cle_produit=cle,
        reference=reference,
        designation=designation,
        unite_brut=ligne.unite_brut,
        unite=unite_code,
        prix_ht=ligne.pu_ht,
        remise_pct=None,
        prix_net=net,
        marque=marque,
        famille=famille,
        date_effet=date_bon,
        source="validation",
        document_id=document.id,
        ligne_libelle=ligne.article_brut,
        auteur_id=auteur_id,
    )
    session.add(nouvelle_ligne)
    await session.flush()

    documents_a_recontroler = {
        a.document_id for a in anomalies if a.document_id is not None
    }
    documents_a_recontroler |= await _documents_prix_ouverts_meme_produit(
        session, fournisseur_id=fournisseur_id, cle_produit=cle_produit_groupe
    )
    nb_reglees = 0
    for anomalie in anomalies:
        ligne_anomalie = await session.get(Ligne, anomalie.ligne_id)
        prix_ligne_anomalie = (
            ligne_anomalie.pu_ht if ligne_anomalie is not None else None
        )
        if prix_ligne_anomalie is None or prix_ligne_anomalie != ligne.pu_ht:
            continue
        avant = _avant_anomalie(anomalie)
        commentaire = f"Prix validé : {_formater_montant(net)} € (grille mise à jour)"
        _fermer_anomalie(
            anomalie, statut="traitee", commentaire=commentaire, auteur_id=auteur_id
        )
        session.add(
            Journal(
                utilisateur_id=auteur_id,
                action="anomalie_traitee",
                cible_table="anomalie",
                cible_id=str(anomalie.id),
                avant=avant,
                apres={"statut": "traitee", "commentaire": commentaire},
            )
        )
        nb_reglees += 1

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="prix_valide",
            cible_table="grille_prix",
            cible_id=str(nouvelle_ligne.id),
            avant={
                "produit": designation,
                "prix_grille": str(ancien_prix_net)
                if ancien_prix_net is not None
                else None,
            },
            apres={
                "produit": designation,
                "prix_grille": str(net),
                "date_effet": date_bon.isoformat(),
                "nb_alertes_reglees": nb_reglees,
            },
        )
    )
    await session.commit()

    for document_id in documents_a_recontroler:
        await controler_prix_bl_sans_echec(session, document_id)

    return ValidationPrixEffectuee(
        prix_net=net, date_effet=date_bon, nb_alertes_reglees=nb_reglees
    )


def _valider_commentaire(commentaire: str) -> str:
    commentaire_normalise = commentaire.strip()
    if not (
        COMMENTAIRE_LONGUEUR_MIN
        <= len(commentaire_normalise)
        <= COMMENTAIRE_LONGUEUR_MAX
    ):
        raise ValueError("commentaire obligatoire (1 à 500 caractères)")
    return commentaire_normalise


async def _fermer_groupe(
    session: AsyncSession,
    *,
    anomalie_ids: Sequence[uuid.UUID],
    statut: str,
    commentaire: str,
    action_journal: str,
    auteur_id: uuid.UUID,
) -> int:
    """Commun à `contester_prix`/`ignorer_prix` : ferme toutes les alertes
    d'un groupe valide (`_charger_groupe`) au même statut et au même
    commentaire, écrit l'entrée `anomalie_traitee`/`anomalie_ignoree`
    habituelle pour chacune, puis une entrée `action_journal` unique pour
    l'action elle-même (spec §8.2 : « l'entrée habituelle ... est aussi
    écrite »). La grille n'est jamais modifiée ici (à la différence de
    `valider_prix`)."""
    anomalies, _fournisseur_id, _cle_produit_groupe = await _charger_groupe(
        session, anomalie_ids
    )

    for anomalie in anomalies:
        avant = _avant_anomalie(anomalie)
        _fermer_anomalie(
            anomalie, statut=statut, commentaire=commentaire, auteur_id=auteur_id
        )
        session.add(
            Journal(
                utilisateur_id=auteur_id,
                action=_ACTION_JOURNAL_PAR_STATUT[statut],
                cible_table="anomalie",
                cible_id=str(anomalie.id),
                avant=avant,
                apres={"statut": statut, "commentaire": commentaire},
            )
        )

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action=action_journal,
            cible_table="anomalie",
            cible_id=str(anomalies[0].id),
            avant=None,
            apres={"commentaire": commentaire, "nb_alertes": len(anomalies)},
        )
    )
    await session.commit()
    return len(anomalies)


# Préfixe du commentaire d'une alerte contestée (spec 2026-10-01 §4.1) :
# seul marqueur d'une contestation, relu par `ingest.contestations_prix`.
PREFIXE_CONTESTATION = "Contesté : "


async def contester_prix(
    session: AsyncSession,
    *,
    anomalie_ids: Sequence[uuid.UUID],
    commentaire: str,
    auteur_id: uuid.UUID,
) -> int:
    """« Contester » (spec §8.2) : commentaire obligatoire, toutes les
    alertes du groupe réglées (`traitee`), grille inchangée. Renvoie le
    nombre d'alertes fermées. Lève `ValueError` (commentaire invalide, 422
    côté routeur) ou `AlertesInvalides` (409)."""
    commentaire_normalise = _valider_commentaire(commentaire)
    return await _fermer_groupe(
        session,
        anomalie_ids=anomalie_ids,
        statut="traitee",
        commentaire=f"{PREFIXE_CONTESTATION}{commentaire_normalise}",
        action_journal="prix_conteste",
        auteur_id=auteur_id,
    )


_COMMENTAIRE_IGNORE_DEFAUT = "Ignoré depuis la page Prix"


async def ignorer_prix(
    session: AsyncSession,
    *,
    anomalie_ids: Sequence[uuid.UUID],
    commentaire: str | None,
    auteur_id: uuid.UUID,
) -> int:
    """« Ignorer » (spec §8.2) : commentaire facultatif (défaut « Ignoré
    depuis la page Prix »), toutes les alertes du groupe réglées
    (`ignoree`), grille inchangée. Renvoie le nombre d'alertes fermées.
    Lève `ValueError` (commentaire trop long, 422) ou `AlertesInvalides`
    (409)."""
    commentaire_normalise = (commentaire or "").strip() or _COMMENTAIRE_IGNORE_DEFAUT
    if len(commentaire_normalise) > COMMENTAIRE_LONGUEUR_MAX:
        raise ValueError("commentaire trop long (500 caractères au plus)")
    return await _fermer_groupe(
        session,
        anomalie_ids=anomalie_ids,
        statut="ignoree",
        commentaire=commentaire_normalise,
        action_journal="prix_ignore",
        auteur_id=auteur_id,
    )


async def recontroler_depuis_page(
    session: AsyncSession, *, auteur_id: uuid.UUID | None
) -> ResultatRecontrolePrix:
    """Bouton « Recontrôler les bons » (spec §8.2, §6.2) : recontrôle tous
    les bons non archivés datés depuis le 1ᵉʳ jour du mois précédent (même
    borne par défaut que la commande CLI `controler-prix`), journalise
    `prix_recontrole` (nombre de bons, d'alertes ouvertes)."""
    borne = _premier_jour_mois_precedent(datetime.now(FUSEAU_PARIS).date())
    resultat = await recontroler_bons(session, depuis=borne)
    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="prix_recontrole",
            cible_table=None,
            cible_id=None,
            avant=None,
            apres={
                "nb_bons": resultat.nb_bons,
                "nb_alertes_ouvertes": resultat.nb_alertes_ouvertes,
            },
        )
    )
    await session.commit()
    return resultat
