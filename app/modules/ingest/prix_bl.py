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
  commande CLI `controler-prix` (spec §6.2). Le recontrôle « bons portant
  une alerte de prix ouverte sur le même produit » (validation d'un prix,
  spec §6.4) n'est pas encore câblé ici : il appartient à la page Prix
  (tâche P8, pas encore construite) -- `ingest.grilles.apres_changement_
  grille` ignore pour l'instant son paramètre `cle_produit_modifiee`.

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
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.anomalies import synchroniser_anomalies
from app.modules.ingest.commun import CLE_ALERTE_PAR_REGLE, CLE_PRIX_CONTROLE_BL_ACTIF
from app.modules.ingest.commun import logger as _logger
from app.modules.ingest.grilles import PrixVigueur, prix_en_vigueur
from app.modules.ingest.models import Anomalie, Article, Document, Ligne
from app.modules.ingest.parametres import DEFINITIONS_PAR_CLE
from app.modules.ingest.referentiels import lire_parametre_decimal
from app.modules.normalize.prix import (
    ProduitGrille,
    normaliser_reference,
    ressemblance_produit,
    trouver_produit,
    unites_comparables,
)
from app.modules.normalize.prix import prix_net as _prix_net_grille
from app.modules.rules.engine import REGLES_PRIX_BL, evaluer_prix_bl
from app.modules.rules.modeles import LignePrixBl, ParametresPrixBl, ReferencePrix

__all__ = [
    "ResultatRecontrolePrix",
    "controler_prix_bl",
    "controler_prix_bl_sans_echec",
    "recontroler_bons",
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


async def _candidats_facture(
    session: AsyncSession, fournisseur_id: uuid.UUID, jusqu_a: date
) -> tuple[_CandidatFacture, ...]:
    """Lignes `article` à `pu_ht > 0` des factures du fournisseur datées au
    plus tard le `jusqu_a` (date du bon, spec §6.3) -- une seule requête par
    bon, réutilisée pour toutes ses lignes."""
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


async def controler_prix_bl(session: AsyncSession, document_id: uuid.UUID) -> int:
    """Contrôle les prix d'un bon face à la grille de son fournisseur et à
    la dernière facture retrouvée (spec §6.1) : renvoie le nombre d'alertes
    de prix ouvertes du bon après contrôle. Ne commite jamais (l'appelant
    tient la transaction, comme `rapprocher_facture`).

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
        session, document.fournisseur_id, date_bon
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
    session: AsyncSession, document_id: uuid.UUID
) -> int | None:
    """Encapsule `controler_prix_bl` pour un déclenchement automatique
    (extraction, correction, changement de grille -- spec §6.2) : commite sa
    propre transaction et ne fait **jamais** échouer l'action appelante --
    toute exception est journalisée (`_journaliser_echec`) puis avalée,
    `None` en retour (même idiome que `ingest.rapprochement
    .rapprocher_facture_sans_echec`)."""
    try:
        nb_ouvertes = await controler_prix_bl(session, document_id)
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

    resultat_ids = await session.execute(select(Document.id).where(*conditions))
    ids = resultat_ids.scalars().all()

    nb_echecs = 0
    total_ouvertes = 0
    for document_id in ids:
        resultat = await controler_prix_bl_sans_echec(session, document_id)
        if resultat is None:
            nb_echecs += 1
        else:
            total_ouvertes += resultat

    return ResultatRecontrolePrix(
        nb_bons=len(ids), nb_echecs=nb_echecs, nb_alertes_ouvertes=total_ouvertes
    )
