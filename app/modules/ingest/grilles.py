"""Grilles de prix fournisseur : lecture (prix en vigueur, historique),
saisie, retrait, import Excel (aperçu puis confirmation) et modèle
téléchargeable -- phase 3, tâche P4, spec
`docs/superpowers/specs/2026-09-27-prix-design.md` §3.2, §7.

Orchestrateur (`ingest`) : seul module métier importé ici en plus de
`extract.grille_excel` (lecture pure du fichier) et `normalize.prix`/
`normalize.unites` (clé produit, prix net, unités -- tous purs). Ce module
porte toute la base et le disque ; `api/grilles.py` (couche d'entrée) ne
fait que valider, appeler et sérialiser (CLAUDE.md).

- `prix_en_vigueur` (spec §3.2) : la brique commune à toute lecture d'un
  prix de grille -- un dict `cle_produit -> PrixVigueur`, calculé pour tous
  les produits du fournisseur (ou seulement ceux de `cles`, quand
  l'appelant sait déjà lesquels l'intéressent -- réutilisé par la tâche P7
  pour ne calculer que les produits des lignes d'un bon). Un produit dont
  la dernière ligne connue à la date demandée est `retire` n'apparaît pas
  dans le résultat, exactement comme un produit jamais importé -- « pas de
  prix à cette date », spec §3.2.
- `lister_grille`/`historique_produit` : lectures pour l'écran « Grille de
  prix d'un fournisseur » (tâche P5) et l'historique d'un produit (jamais
  affiché, « interrogeable » seulement, spec §7.4).
- `enregistrer_prix`/`retirer_produit` : saisie et retrait manuels (spec
  §7.4), chacun une ligne `grille_prix` de plus (source `"saisie"` --
  aucune valeur `'retrait'` dans la contrainte `CHECK` de la migration
  0013 : un retrait est une saisie comme une autre, seul `retire=True` le
  distingue).
- `apercu_import`/`importer_grille` : lecture d'un fichier Excel, comparaison
  au prix en vigueur à la date d'effet choisie (spec §7.2), puis, pour
  `importer_grille` seulement, écriture (fichier copié sous
  `DOCS_DIR/grilles/<fournisseur_id>/`, lignes `grille_prix` des produits
  nouveaux ou modifiés, `grille_import`, journal).
- `modele_excel` : classeur généré à la volée (jamais un fichier du
  client), toujours relisible par `extract.grille_excel.lire_grille_excel`
  sans erreur (spec §7.3).
- `apres_changement_grille` : point d'accroche du recontrôle des bons
  après un changement de grille (spec §6.4, câblé par la tâche P7 sur
  `ingest.prix_bl.recontroler_bons`, import différé pour éviter un cycle).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import ceil
from pathlib import Path

import openpyxl
from openpyxl.styles import Font
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.extract.grille_excel import (
    FichierGrilleInvalide,
    GrilleLue,
    LigneGrilleLue,
    lire_grille_excel,
)
from app.modules.ingest.commun import (
    _creer_dossier_documents,
    _ecrire_atomique,
    _supprimer_si_existe,
)
from app.modules.ingest.models import (
    Fournisseur,
    GrilleImport,
    GrillePrix,
    Journal,
    Utilisateur,
)
from app.modules.normalize.prix import cle_produit, prix_net
from app.modules.normalize.texte import normaliser_libelle
from app.modules.normalize.unites import normaliser_unite

__all__ = [
    "ApercuImport",
    "AucuneLigneValide",
    "EcritureImpossible",
    "ErreurImport",
    "FichierGrilleInvalide",
    "FournisseurIntrouvable",
    "GrilleFournisseur",
    "ImportEffectue",
    "LigneComparee",
    "LigneHistorique",
    "PrixInchange",
    "PrixVigueur",
    "ProduitAbsent",
    "ProduitGrilleAffiche",
    "ProduitIntrouvable",
    "SaisieInvalide",
    "SaisiePrix",
    "apercu_import",
    "apres_changement_grille",
    "enregistrer_prix",
    "historique_produit",
    "importer_grille",
    "lister_grille",
    "modele_excel",
    "prix_en_vigueur",
    "retirer_produit",
]

# 50 produits par page (spec §9) -- utilisé aussi bien pour la pagination de
# l'écran que pour calculer le nombre de pages renvoyé par `lister_grille`.
PRODUITS_PAGE_TAILLE = 50

# Bornes de la date d'effet d'un import (spec §7.2).
_DATE_EFFET_MIN = date(2000, 1, 1)


class FournisseurIntrouvable(Exception):
    """Le `fournisseur_id` ne correspond à aucun fournisseur connu."""


class ProduitIntrouvable(Exception):
    """Le produit demandé (`cle_produit`) n'a aucune ligne dans la grille de
    ce fournisseur (retrait) ou aucun historique (`historique_produit`)."""


class SaisieInvalide(Exception):
    """La saisie (prix, remise, date d'effet…) ne peut pas être enregistrée
    telle quelle -- message déjà prêt pour l'écran."""


class PrixInchange(Exception):
    """Le prix saisi est déjà celui en vigueur à cette date (spec §7.4)."""


class AucuneLigneValide(Exception):
    """Le fichier de grille ne contient aucune ligne de produit valide."""


class EcritureImpossible(Exception):
    """Échec de l'écriture du fichier de grille sur disque (`OSError`, ex.
    disque plein) -- même principe que `ingest.factures.EcritureImpossible`."""


def _valider_date_effet(date_effet: date) -> None:
    """Bornes de la date d'effet d'un import (spec §7.2) : entre le
    01/01/2000 et aujourd'hui (Europe/Paris) + 1 an.

    Le 29 février, `aujourdhui.replace(year=...)` lève `ValueError` si
    l'année suivante n'est pas bissextile (constat de la relecture
    qualité) : on ramène alors la borne au 28 février de cette année-là,
    au lieu de laisser filer une `ValueError` que les routeurs ne
    rattrapent pas (seule `SaisieInvalide` devient une 422 dans
    `api/grilles.py`)."""
    aujourdhui = datetime.now(FUSEAU_PARIS).date()
    try:
        date_max = aujourdhui.replace(year=aujourdhui.year + 1)
    except ValueError:
        date_max = aujourdhui.replace(year=aujourdhui.year + 1, day=28)
    if date_effet < _DATE_EFFET_MIN or date_effet > date_max:
        raise SaisieInvalide(
            "La date d'effet doit être comprise entre le 01/01/2000 et un an "
            "à partir d'aujourd'hui."
        )


async def _verifier_fournisseur(
    session: AsyncSession, fournisseur_id: uuid.UUID
) -> Fournisseur:
    fournisseur = await session.get(Fournisseur, fournisseur_id)
    if fournisseur is None:
        raise FournisseurIntrouvable(str(fournisseur_id))
    return fournisseur


# --------------------------------------------------------------------------
# Prix en vigueur (spec §3.2) : la brique commune à toute lecture.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PrixVigueur:
    """Le prix d'un produit considéré « en vigueur » à une date donnée
    (`prix_en_vigueur`) : la ligne `grille_prix` de plus grande `date_effet`
    inférieure ou égale à la date demandée (à égalité, la plus récente en
    `created_at`), ou, à défaut, la première ligne postérieure --
    `posterieure` le signale alors (spec §3.2, « grille postérieure au
    bon »). Un produit dont la ligne choisie est `retire` n'a pas de
    `PrixVigueur` du tout (absent du dict rendu par `prix_en_vigueur`)."""

    cle_produit: str
    reference: str | None
    designation: str
    unite_brut: str | None
    unite: str | None
    prix_ht: Decimal
    remise_pct: Decimal | None
    prix_net: Decimal
    marque: str | None
    famille: str | None
    date_effet: date
    posterieure: bool


async def prix_en_vigueur(
    session: AsyncSession,
    fournisseur_id: uuid.UUID,
    a_la_date: date,
    cles: Iterable[str] | None = None,
) -> dict[str, PrixVigueur]:
    """Prix en vigueur à `a_la_date` de chaque produit de la grille de
    `fournisseur_id` (ou seulement ceux de `cles`, si fourni -- réutilisé
    par la tâche P7 pour ne calculer que les produits des lignes d'un bon).

    Algorithme (spec §3.2) : parmi toutes les lignes d'un même
    `cle_produit`, celle de plus grande `date_effet <= a_la_date` (à
    égalité, la plus récente en `created_at`) ; si aucune ligne n'a de
    `date_effet <= a_la_date` mais qu'il en existe une plus tard (grille
    importée après la date considérée), la première ligne postérieure
    (plus petite `date_effet`, à égalité la plus ancienne en `created_at`)
    -- `posterieure=True`. Une ligne choisie `retire` exclut le produit du
    résultat, dans les deux cas."""
    conditions = [GrillePrix.fournisseur_id == fournisseur_id]
    if cles is not None:
        cles_tuple = tuple(cles)
        if not cles_tuple:
            return {}
        conditions.append(GrillePrix.cle_produit.in_(cles_tuple))

    resultat = await session.execute(
        select(GrillePrix)
        .where(*conditions)
        .order_by(
            GrillePrix.cle_produit.asc(),
            GrillePrix.date_effet.desc(),
            GrillePrix.created_at.desc(),
        )
    )
    lignes = resultat.scalars().all()

    par_produit: dict[str, list[GrillePrix]] = {}
    for ligne in lignes:
        par_produit.setdefault(ligne.cle_produit, []).append(ligne)

    resultats: dict[str, PrixVigueur] = {}
    for cle, groupe in par_produit.items():
        avant = [g for g in groupe if g.date_effet <= a_la_date]
        if avant:
            # `groupe` est déjà trié (date_effet desc, created_at desc) :
            # le premier de `avant` est la ligne en vigueur (spec §3.2).
            choisie = avant[0]
            posterieure = False
        else:
            apres = [g for g in groupe if g.date_effet > a_la_date]
            if not apres:
                continue
            choisie = min(apres, key=lambda g: (g.date_effet, g.created_at))
            posterieure = True

        if choisie.retire:
            continue

        resultats[cle] = PrixVigueur(
            cle_produit=cle,
            reference=choisie.reference,
            designation=choisie.designation,
            unite_brut=choisie.unite_brut,
            unite=choisie.unite,
            prix_ht=choisie.prix_ht,
            remise_pct=choisie.remise_pct,
            prix_net=choisie.prix_net,
            marque=choisie.marque,
            famille=choisie.famille,
            date_effet=choisie.date_effet,
            posterieure=posterieure,
        )
    return resultats


# --------------------------------------------------------------------------
# Écran « Grille de prix d'un fournisseur » (spec §9, tâche P5) : liste
# paginée des prix en vigueur aujourd'hui, avec recherche.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProduitGrilleAffiche:
    """Une ligne de `GET /api/grilles/fournisseurs/{id}` -- aussi le retour
    de `enregistrer_prix`/`retirer_produit` (même forme, la ligne créée)."""

    cle_produit: str
    reference: str | None
    designation: str
    unite_brut: str | None
    prix_ht: Decimal
    remise_pct: Decimal | None
    prix_net: Decimal
    marque: str | None
    famille: str | None
    date_effet: date


@dataclass(frozen=True)
class GrilleFournisseur:
    """Réponse complète de `GET /api/grilles/fournisseurs/{id}` : l'en-tête
    de l'écran (spec §9 : nom, nombre de produits, date du dernier import)
    et la page de produits demandée."""

    fournisseur_id: uuid.UUID
    nom_fournisseur: str
    nb_produits: int
    dernier_import_le: datetime | None
    page: int
    pages: int
    produits: tuple[ProduitGrilleAffiche, ...]


def _en_affiche(produit: PrixVigueur) -> ProduitGrilleAffiche:
    return ProduitGrilleAffiche(
        cle_produit=produit.cle_produit,
        reference=produit.reference,
        designation=produit.designation,
        unite_brut=produit.unite_brut,
        prix_ht=produit.prix_ht,
        remise_pct=produit.remise_pct,
        prix_net=produit.prix_net,
        marque=produit.marque,
        famille=produit.famille,
        date_effet=produit.date_effet,
    )


async def _dernier_import(
    session: AsyncSession, fournisseur_id: uuid.UUID
) -> datetime | None:
    resultat = await session.execute(
        select(func.max(GrilleImport.created_at)).where(
            GrilleImport.fournisseur_id == fournisseur_id
        )
    )
    return resultat.scalar_one_or_none()


async def lister_grille(
    session: AsyncSession,
    fournisseur_id: uuid.UUID,
    recherche: str | None = None,
    page: int = 1,
) -> GrilleFournisseur:
    """Prix en vigueur aujourd'hui (Europe/Paris) du fournisseur, filtrés
    par `recherche` (référence ou désignation, insensible à la casse et aux
    accents -- `normalize.prix.normaliser_reference`/`normalize.texte
    .normaliser_libelle`) et paginés (`PRODUITS_PAGE_TAILLE` par page, spec
    §9). Triés par désignation. Lève `FournisseurIntrouvable` si
    `fournisseur_id` est inconnu."""
    fournisseur = await _verifier_fournisseur(session, fournisseur_id)
    aujourdhui = datetime.now(FUSEAU_PARIS).date()
    vigueur = await prix_en_vigueur(session, fournisseur_id, aujourdhui)
    nb_produits = len(vigueur)

    produits = list(vigueur.values())
    if recherche and recherche.strip():
        motif = normaliser_libelle(recherche)
        motif_sans_espaces = motif.replace(" ", "")
        produits = [
            p
            for p in produits
            if (motif and motif in normaliser_libelle(p.designation))
            or (
                p.reference is not None
                and motif_sans_espaces
                and motif_sans_espaces
                in normaliser_libelle(p.reference).replace(" ", "")
            )
        ]

    produits.sort(key=lambda p: normaliser_libelle(p.designation))

    total = len(produits)
    pages = max(1, ceil(total / PRODUITS_PAGE_TAILLE)) if total else 1
    page_effective = max(1, page)
    debut = (page_effective - 1) * PRODUITS_PAGE_TAILLE
    page_produits = produits[debut : debut + PRODUITS_PAGE_TAILLE]

    dernier_import_le = await _dernier_import(session, fournisseur_id)

    return GrilleFournisseur(
        fournisseur_id=fournisseur_id,
        nom_fournisseur=fournisseur.nom,
        nb_produits=nb_produits,
        dernier_import_le=dernier_import_le,
        page=page_effective,
        pages=pages,
        produits=tuple(_en_affiche(p) for p in page_produits),
    )


@dataclass(frozen=True)
class LigneHistorique:
    """Une ligne de `GET /api/grilles/fournisseurs/{id}/produits/{cle}
    /historique` (spec §7.4 : « API seulement, pas d'écran »), de la plus
    récente à la plus ancienne."""

    id: uuid.UUID
    reference: str | None
    designation: str
    unite_brut: str | None
    unite: str | None
    prix_ht: Decimal
    remise_pct: Decimal | None
    prix_net: Decimal
    marque: str | None
    famille: str | None
    date_effet: date
    retire: bool
    source: str
    document_id: uuid.UUID | None
    ligne_libelle: str | None
    auteur: str | None
    created_at: datetime


async def historique_produit(
    session: AsyncSession, fournisseur_id: uuid.UUID, cle_produit_recherchee: str
) -> tuple[LigneHistorique, ...]:
    """Tout l'historique d'un produit, de la plus récente à la plus
    ancienne (`date_effet` puis `created_at`, décroissants). `auteur` :
    `nom` ou, à défaut, `email` de `auteur_id` (même convention que
    `JournalLue.auteur`/`AnomalieLue.traitee_par`), `None` pour une ligne
    sans auteur (import automatique, décision non prise par un humain).
    Lève `FournisseurIntrouvable`, ou `ProduitIntrouvable` si ce produit
    n'a jamais eu la moindre ligne dans la grille de ce fournisseur."""
    await _verifier_fournisseur(session, fournisseur_id)
    resultat = await session.execute(
        select(GrillePrix, Utilisateur)
        .outerjoin(Utilisateur, Utilisateur.id == GrillePrix.auteur_id)
        .where(
            GrillePrix.fournisseur_id == fournisseur_id,
            GrillePrix.cle_produit == cle_produit_recherchee,
        )
        .order_by(GrillePrix.date_effet.desc(), GrillePrix.created_at.desc())
    )
    lignes = resultat.all()
    if not lignes:
        raise ProduitIntrouvable(cle_produit_recherchee)

    return tuple(
        LigneHistorique(
            id=ligne.id,
            reference=ligne.reference,
            designation=ligne.designation,
            unite_brut=ligne.unite_brut,
            unite=ligne.unite,
            prix_ht=ligne.prix_ht,
            remise_pct=ligne.remise_pct,
            prix_net=ligne.prix_net,
            marque=ligne.marque,
            famille=ligne.famille,
            date_effet=ligne.date_effet,
            retire=ligne.retire,
            source=ligne.source,
            document_id=ligne.document_id,
            ligne_libelle=ligne.ligne_libelle,
            auteur=(utilisateur.nom or utilisateur.email)
            if utilisateur is not None
            else None,
            created_at=ligne.created_at,
        )
        for ligne, utilisateur in lignes
    )


# --------------------------------------------------------------------------
# Saisie et retrait à l'écran (spec §7.4).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SaisiePrix:
    """Saisie manuelle d'un prix (spec §7.4) : `date_effet` est déjà
    résolue par l'appelant (`api/grilles.py` : aujourd'hui si absente de la
    requête)."""

    designation: str
    prix_ht: Decimal
    date_effet: date
    reference: str | None = None
    unite: str | None = None
    remise_pct: Decimal | None = None
    marque: str | None = None
    famille: str | None = None


def _avant_json(existant: PrixVigueur | None) -> dict[str, str] | None:
    if existant is None:
        return None
    return {
        "prix_net": str(existant.prix_net),
        "date_effet": existant.date_effet.isoformat(),
    }


async def enregistrer_prix(
    session: AsyncSession,
    fournisseur_id: uuid.UUID,
    saisie: SaisiePrix,
    *,
    auteur_id: uuid.UUID | None,
) -> ProduitGrilleAffiche:
    """Enregistre un prix saisi à l'écran : même produit (clé, spec §4.1)
    -> nouvelle ligne `source="saisie"` (l'historique n'est jamais modifié).
    Lève `FournisseurIntrouvable`, `SaisieInvalide` (désignation vide, prix
    ou remise invalides -- `normalize.prix.prix_net`) ou `PrixInchange`
    (422 : « ce prix est déjà celui de la grille », même prix net et même
    unité que le prix en vigueur à cette date). Ne commite pas le
    recontrôle (§6.4) avant d'avoir elle-même commité."""
    await _verifier_fournisseur(session, fournisseur_id)

    designation = saisie.designation.strip()
    if not designation:
        raise SaisieInvalide("La désignation est obligatoire.")
    reference = (saisie.reference or "").strip() or None

    try:
        net = prix_net(saisie.prix_ht, saisie.remise_pct)
    except ValueError as exc:
        raise SaisieInvalide(str(exc)) from exc

    cle = cle_produit(reference, designation)
    unite_normalisee = normaliser_unite(saisie.unite)
    unite_code = unite_normalisee.code if unite_normalisee is not None else None

    vigueur = await prix_en_vigueur(
        session, fournisseur_id, saisie.date_effet, cles=(cle,)
    )
    existant = vigueur.get(cle)
    if (
        existant is not None
        and existant.prix_net == net
        and existant.unite == unite_code
    ):
        raise PrixInchange("Ce prix est déjà celui de la grille.")

    unite_brut = (saisie.unite or "").strip() or None
    marque = (saisie.marque or "").strip() or None
    famille = (saisie.famille or "").strip() or None

    ligne = GrillePrix(
        fournisseur_id=fournisseur_id,
        cle_produit=cle,
        reference=reference,
        designation=designation,
        unite_brut=unite_brut,
        unite=unite_code,
        prix_ht=saisie.prix_ht,
        remise_pct=saisie.remise_pct,
        prix_net=net,
        marque=marque,
        famille=famille,
        date_effet=saisie.date_effet,
        source="saisie",
        auteur_id=auteur_id,
    )
    session.add(ligne)
    await session.flush()

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="grille_prix_saisi",
            cible_table="grille_prix",
            cible_id=str(ligne.id),
            avant=_avant_json(existant),
            apres={
                "designation": designation,
                "prix_net": str(net),
                "date_effet": saisie.date_effet.isoformat(),
            },
        )
    )
    await session.commit()

    await apres_changement_grille(
        session, fournisseur_id=fournisseur_id, date_effet=saisie.date_effet
    )

    return ProduitGrilleAffiche(
        cle_produit=cle,
        reference=reference,
        designation=designation,
        unite_brut=unite_brut,
        prix_ht=saisie.prix_ht,
        remise_pct=saisie.remise_pct,
        prix_net=net,
        marque=marque,
        famille=famille,
        date_effet=saisie.date_effet,
    )


async def retirer_produit(
    session: AsyncSession,
    fournisseur_id: uuid.UUID,
    cle_produit_a_retirer: str,
    date_effet: date,
    *,
    auteur_id: uuid.UUID | None,
) -> None:
    """Retire un produit de la grille (spec §7.4) : nouvelle ligne
    `retire=True` reprenant le dernier prix connu (contrainte `prix_ht >
    0` -- une ligne `retire` garde le prix qu'elle remplace, jamais un
    prix à 0). Lève `FournisseurIntrouvable`, ou `ProduitIntrouvable` si le
    produit n'a pas de prix en vigueur à `date_effet` (rien à retirer)."""
    await _verifier_fournisseur(session, fournisseur_id)

    vigueur = await prix_en_vigueur(
        session, fournisseur_id, date_effet, cles=(cle_produit_a_retirer,)
    )
    existant = vigueur.get(cle_produit_a_retirer)
    if existant is None:
        raise ProduitIntrouvable(cle_produit_a_retirer)

    ligne = GrillePrix(
        fournisseur_id=fournisseur_id,
        cle_produit=cle_produit_a_retirer,
        reference=existant.reference,
        designation=existant.designation,
        unite_brut=existant.unite_brut,
        unite=existant.unite,
        prix_ht=existant.prix_ht,
        remise_pct=existant.remise_pct,
        prix_net=existant.prix_net,
        marque=existant.marque,
        famille=existant.famille,
        date_effet=date_effet,
        retire=True,
        source="saisie",
        auteur_id=auteur_id,
    )
    session.add(ligne)
    await session.flush()

    session.add(
        Journal(
            utilisateur_id=auteur_id,
            action="grille_prix_retire",
            cible_table="grille_prix",
            cible_id=str(ligne.id),
            avant={
                "designation": existant.designation,
                "prix_net": str(existant.prix_net),
            },
            apres={"date_effet": date_effet.isoformat()},
        )
    )
    await session.commit()


# --------------------------------------------------------------------------
# Import d'un fichier Excel (spec §7.2) : aperçu (aucune écriture) puis
# confirmation, comparaison identique dans les deux cas.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class LigneComparee:
    """Une ligne « nouveau » ou « modifié » d'un aperçu d'import (spec
    §7.2) : `ancien_prix_net`/`ancienne_unite` valent `None` pour un
    produit nouveau."""

    reference: str | None
    designation: str
    nouveau_prix_net: Decimal
    ancien_prix_net: Decimal | None
    nouvelle_unite: str | None
    ancienne_unite: str | None


@dataclass(frozen=True)
class ProduitAbsent:
    """Un produit en vigueur qui ne figure pas dans le fichier importé --
    information seulement, il n'est jamais retiré (spec §7.2)."""

    reference: str | None
    designation: str
    prix_net: Decimal


@dataclass(frozen=True)
class ErreurImport:
    """Une ligne du fichier qui n'a pas pu être retenue -- mêmes attributs
    qu'`extract.grille_excel.ErreurGrille`."""

    feuille: str
    numero_ligne: int
    message: str


@dataclass(frozen=True)
class ApercuImport:
    """Résultat de `apercu_import` : ne modifie jamais la base (spec §7.2)."""

    nb_nouveaux: int
    nb_modifies: int
    nb_inchanges: int
    nb_erreurs: int
    nouveaux: tuple[LigneComparee, ...]
    modifies: tuple[LigneComparee, ...]
    absents_du_fichier: tuple[ProduitAbsent, ...]
    erreurs: tuple[ErreurImport, ...]
    feuilles_ignorees: tuple[str, ...]


@dataclass(frozen=True)
class ImportEffectue:
    """Résultat de `importer_grille` : les mêmes compteurs que l'aperçu,
    figés dans `grille_import` (spec §3.1)."""

    import_id: uuid.UUID
    nb_nouveaux: int
    nb_modifies: int
    nb_inchanges: int
    nb_erreurs: int


@dataclass(frozen=True)
class _LigneAnalysee:
    """Le résultat de la comparaison d'une `LigneGrilleLue` au prix en
    vigueur à la date d'effet demandée -- aide interne partagée par
    `apercu_import` et `importer_grille` (même calcul, spec §7.2 : «
    relit le fichier (même calcul) »)."""

    ligne: LigneGrilleLue
    cle: str
    prix_net: Decimal
    unite_code: str | None
    comparee: LigneComparee
    statut: str  # "nouveau" | "modifie" | "inchange"


def _analyser_lignes(
    produits_en_vigueur: dict[str, PrixVigueur], lignes: Sequence[LigneGrilleLue]
) -> list[_LigneAnalysee]:
    analyses: list[_LigneAnalysee] = []
    for ligne in lignes:
        cle = cle_produit(ligne.reference, ligne.designation)
        # `lire_grille_excel` a déjà validé `prix_ht > 0` et la remise dans
        # `[0, 100[` : `prix_net` ne peut pas lever ici.
        net = prix_net(ligne.prix_ht, ligne.remise_pct)
        unite_normalisee = normaliser_unite(ligne.unite_brut)
        unite_code = unite_normalisee.code if unite_normalisee is not None else None
        existant = produits_en_vigueur.get(cle)

        comparee = LigneComparee(
            reference=ligne.reference,
            designation=ligne.designation,
            nouveau_prix_net=net,
            ancien_prix_net=existant.prix_net if existant is not None else None,
            nouvelle_unite=unite_code,
            ancienne_unite=existant.unite if existant is not None else None,
        )
        if existant is None:
            statut = "nouveau"
        elif existant.prix_net != net or existant.unite != unite_code:
            statut = "modifie"
        else:
            statut = "inchange"

        analyses.append(_LigneAnalysee(ligne, cle, net, unite_code, comparee, statut))
    return analyses


async def _comparer_fichier(
    session: AsyncSession, fournisseur_id: uuid.UUID, contenu: bytes, date_effet: date
) -> tuple[GrilleLue, list[_LigneAnalysee], dict[str, PrixVigueur]]:
    """Lecture du fichier puis comparaison au prix en vigueur à
    `date_effet` -- calcul unique, partagé par `apercu_import` et
    `importer_grille` (« relit le fichier (même calcul) », spec §7.2).
    Peut lever `FichierGrilleInvalide` (`extract.grille_excel`)."""
    grille_lue = lire_grille_excel(contenu)
    produits_en_vigueur = await prix_en_vigueur(session, fournisseur_id, date_effet)
    analyses = _analyser_lignes(produits_en_vigueur, grille_lue.lignes)
    return grille_lue, analyses, produits_en_vigueur


def _absents_du_fichier(
    analyses: list[_LigneAnalysee], produits_en_vigueur: dict[str, PrixVigueur]
) -> tuple[ProduitAbsent, ...]:
    cles_fichier = {analyse.cle for analyse in analyses}
    absents = [
        ProduitAbsent(
            reference=produit.reference,
            designation=produit.designation,
            prix_net=produit.prix_net,
        )
        for cle, produit in produits_en_vigueur.items()
        if cle not in cles_fichier
    ]
    absents.sort(key=lambda p: normaliser_libelle(p.designation))
    return tuple(absents)


async def apercu_import(
    session: AsyncSession,
    fournisseur_id: uuid.UUID,
    contenu: bytes,
    nom_fichier: str,
    date_effet: date,
) -> ApercuImport:
    """Aperçu d'un import (spec §7.2) : ne modifie jamais la base. Compare
    chaque ligne lue au prix en vigueur à `date_effet` du même produit --
    voir les docstrings de `LigneComparee`/`ProduitAbsent`. Lève
    `FournisseurIntrouvable`, `SaisieInvalide` (date d'effet hors bornes)
    ou `FichierGrilleInvalide` (`extract.grille_excel`, fichier illisible)."""
    del nom_fichier  # non nécessaire pour l'aperçu, symétrie avec `importer_grille`
    await _verifier_fournisseur(session, fournisseur_id)
    _valider_date_effet(date_effet)

    grille_lue, analyses, produits_en_vigueur = await _comparer_fichier(
        session, fournisseur_id, contenu, date_effet
    )

    nouveaux = tuple(a.comparee for a in analyses if a.statut == "nouveau")
    modifies = tuple(a.comparee for a in analyses if a.statut == "modifie")
    nb_inchanges = sum(1 for a in analyses if a.statut == "inchange")

    return ApercuImport(
        nb_nouveaux=len(nouveaux),
        nb_modifies=len(modifies),
        nb_inchanges=nb_inchanges,
        nb_erreurs=len(grille_lue.erreurs),
        nouveaux=nouveaux,
        modifies=modifies,
        absents_du_fichier=_absents_du_fichier(analyses, produits_en_vigueur),
        erreurs=tuple(
            ErreurImport(
                feuille=e.feuille, numero_ligne=e.numero_ligne, message=e.message
            )
            for e in grille_lue.erreurs
        ),
        feuilles_ignorees=grille_lue.feuilles_ignorees,
    )


async def importer_grille(
    session: AsyncSession,
    fournisseur_id: uuid.UUID,
    contenu: bytes,
    nom_fichier: str,
    date_effet: date,
    *,
    auteur_id: uuid.UUID | None,
    docs_dir: Path,
) -> ImportEffectue:
    """Confirme un import (spec §7.2) : relit le fichier (même calcul que
    `apercu_import`), refuse s'il n'y a aucune ligne valide
    (`AucuneLigneValide`), puis dans **une** transaction -- `grille_import`,
    une ligne `grille_prix` (`source="import"`) par produit nouveau ou
    modifié (les inchangés ne créent aucune ligne : un import au contenu
    identique au précédent n'écrit donc rien de plus qu'un `grille_import`),
    copie du fichier sous `DOCS_DIR/grilles/<fournisseur_id>/` (0640, via
    `ingest.commun._ecrire_atomique`) et journal `grille_importee`. Recontrôle
    ensuite les bons concernés (spec §6.4, `apres_changement_grille`).

    Lève `FournisseurIntrouvable`, `SaisieInvalide` (date d'effet hors
    bornes), `FichierGrilleInvalide` (fichier illisible), `AucuneLigneValide`
    ou `EcritureImpossible` (échec de l'écriture disque)."""
    await _verifier_fournisseur(session, fournisseur_id)
    _valider_date_effet(date_effet)

    grille_lue, analyses, _produits_en_vigueur = await _comparer_fichier(
        session, fournisseur_id, contenu, date_effet
    )
    if not grille_lue.lignes:
        raise AucuneLigneValide(
            "Le fichier ne contient aucune ligne de produit valide."
        )

    a_inserer = [a for a in analyses if a.statut != "inchange"]
    nb_nouveaux = sum(1 for a in analyses if a.statut == "nouveau")
    nb_modifies = sum(1 for a in analyses if a.statut == "modifie")
    nb_inchanges = sum(1 for a in analyses if a.statut == "inchange")
    nb_erreurs = len(grille_lue.erreurs)

    empreinte = hashlib.sha256(contenu).hexdigest()
    dossier_grilles = docs_dir / "grilles"
    dossier_fournisseur = dossier_grilles / str(fournisseur_id)
    # Connu seulement une fois `grille_import` inséré (voir plus bas) : le
    # nom sur disque doit reprendre l'id réel de l'import (spec §3.1), pas un
    # UUID généré à part qui ne lui correspondrait jamais (constat de la
    # relecture qualité). `None` tant que rien n'a été écrit, pour que le
    # nettoyage du `except` ci-dessous ne tente de supprimer un fichier que
    # si son écriture a pu commencer.
    chemin_final: Path | None = None

    try:
        fournisseur = await _verifier_fournisseur(session, fournisseur_id)
        grille_import = GrilleImport(
            fournisseur_id=fournisseur_id,
            nom_fichier=nom_fichier[:200],
            empreinte=empreinte,
            chemin="",  # complété ci-dessous, une fois l'id connu
            date_effet=date_effet,
            nb_nouveaux=nb_nouveaux,
            nb_modifies=nb_modifies,
            nb_inchanges=nb_inchanges,
            nb_erreurs=nb_erreurs,
            auteur_id=auteur_id,
        )
        session.add(grille_import)
        await session.flush()
        import_id = grille_import.id

        chemin_final = (dossier_fournisseur / f"{import_id}.xlsx").absolute()
        chemin_temporaire = (dossier_fournisseur / f"{import_id}.xlsx.tmp").absolute()
        grille_import.chemin = str(chemin_final)

        try:
            # `dossier_grilles` (`docs_dir/grilles`) est créé ici
            # explicitement, avant `dossier_fournisseur` : `Path.mkdir(parents=True)`
            # n'applique le mode voulu qu'au dossier terminal, jamais aux
            # parents manquants qu'il crée au passage (ils héritent des
            # droits par défaut, ignorant `mode` -- constat de la relecture
            # qualité). Sans cet appel, `_creer_dossier_documents(dossier_fournisseur)`
            # dans `_ecrire_atomique` créerait `dossier_grilles` en 0755
            # (umask 0022 du conteneur) au premier import, listable par tout
            # autre compte Unix du VPS partagé -- régression vis-à-vis de la
            # tâche T3 du 25/09/2026. Une fois `dossier_grilles` présent en
            # 0750, le second appel (dans `_ecrire_atomique`) ne crée plus
            # qu'un seul niveau (`dossier_fournisseur`), qui reçoit bien le
            # mode voulu.
            await asyncio.to_thread(_creer_dossier_documents, dossier_grilles)
            await asyncio.to_thread(
                _ecrire_atomique,
                dossier_fournisseur,
                chemin_temporaire,
                chemin_final,
                contenu,
            )
        except OSError as exc:
            await asyncio.to_thread(_supprimer_si_existe, chemin_temporaire)
            raise EcritureImpossible(
                "Enregistrement du fichier de grille impossible, réessayez."
            ) from exc

        for analyse in a_inserer:
            session.add(
                GrillePrix(
                    fournisseur_id=fournisseur_id,
                    cle_produit=analyse.cle,
                    reference=analyse.ligne.reference,
                    designation=analyse.ligne.designation,
                    unite_brut=analyse.ligne.unite_brut,
                    unite=analyse.unite_code,
                    prix_ht=analyse.ligne.prix_ht,
                    remise_pct=analyse.ligne.remise_pct,
                    prix_net=analyse.prix_net,
                    marque=analyse.ligne.marque,
                    famille=analyse.ligne.famille,
                    date_effet=date_effet,
                    source="import",
                    import_id=import_id,
                    auteur_id=auteur_id,
                )
            )

        session.add(
            Journal(
                utilisateur_id=auteur_id,
                action="grille_importee",
                cible_table="grille_import",
                cible_id=str(import_id),
                avant=None,
                apres={
                    "fournisseur": fournisseur.nom,
                    "nom_fichier": nom_fichier,
                    "date_effet": date_effet.isoformat(),
                    "nb_nouveaux": nb_nouveaux,
                    "nb_modifies": nb_modifies,
                    "nb_inchanges": nb_inchanges,
                    "nb_erreurs": nb_erreurs,
                },
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()
        if chemin_final is not None:
            await asyncio.to_thread(_supprimer_si_existe, chemin_final)
        raise

    await apres_changement_grille(
        session, fournisseur_id=fournisseur_id, date_effet=date_effet
    )

    return ImportEffectue(
        import_id=import_id,
        nb_nouveaux=nb_nouveaux,
        nb_modifies=nb_modifies,
        nb_inchanges=nb_inchanges,
        nb_erreurs=nb_erreurs,
    )


# --------------------------------------------------------------------------
# Modèle Excel téléchargeable (spec §7.3) : jamais un fichier du client,
# toujours relisible sans erreur par `extract.grille_excel.lire_grille_excel`.
# --------------------------------------------------------------------------

_ENTETES_MODELE = (
    "Référence",
    "Désignation",
    "Unité",
    "Prix unitaire HT (€)",
    "Remise %",
    "Marque",
    "Famille",
)

_LARGEURS_MODELE = {"A": 16, "B": 42, "C": 10, "D": 20, "E": 10, "F": 20, "G": 20}

_PHRASES_MODE_EMPLOI = (
    "Référence : facultative — code article du fournisseur, laissée vide si "
    "l'article n'en a pas.",
    "Désignation : obligatoire — nom du produit tel qu'il doit apparaître "
    "dans la grille.",
    "Unité : facultative — unité de vente (ex. m, sac, boîte, rouleau, unité).",
    "Prix unitaire HT : obligatoire — nombre ou texte (« 6,30 » ou « 6.30 € » "
    "sont acceptés), toujours strictement supérieur à 0.",
    "Remise % : facultative — pourcentage compris entre 0 et 100 (exclu).",
    "Marque : facultative.",
    "Famille : facultative — absente, elle reprend le nom de la feuille.",
    "Le fournisseur et la date d'effet de cette grille se choisissent au "
    "moment de l'import, pas dans ce fichier.",
)


def modele_excel() -> bytes:
    """Classeur modèle (spec §7.3), généré à la volée avec `openpyxl` --
    jamais un fichier du client. Feuille « Grille » : en-tête en gras, deux
    lignes d'exemple inventées (une avec référence et remise, une sans
    référence avec unité) ; feuille « Mode d'emploi » (une phrase par
    colonne, ignorée à l'import faute d'en-tête reconnu -- le mode d'emploi
    dit d'effacer les deux exemples avant de remplir le fichier)."""
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    if feuille is None:
        # Toujours faux pour un classeur `openpyxl.Workbook()` fraîchement
        # créé (une feuille active existe toujours) -- défensif, jamais un
        # `assert` (S101) dans du code de production.
        raise RuntimeError("classeur sans feuille active")
    feuille.title = "Grille"

    feuille.append(_ENTETES_MODELE)
    for cellule in feuille[1]:
        cellule.font = Font(bold=True)

    feuille.append(
        (
            "REF-INV-0001",
            "Exemple avec référence et remise",
            None,
            12.5,
            10,
            "Marque inventée",
            "Famille inventée",
        )
    )
    feuille.append(
        (None, "Exemple sans référence, avec unité", "sac", 7.9, None, None, None)
    )
    for ligne_cellules in feuille.iter_rows(min_row=2, min_col=4, max_col=4):
        for cellule in ligne_cellules:
            cellule.number_format = "0.00"

    for colonne, largeur in _LARGEURS_MODELE.items():
        feuille.column_dimensions[colonne].width = largeur

    mode_emploi = classeur.create_sheet("Mode d'emploi")
    for phrase in _PHRASES_MODE_EMPLOI:
        mode_emploi.append((phrase,))
    mode_emploi.column_dimensions["A"].width = 100

    tampon = io.BytesIO()
    classeur.save(tampon)
    return tampon.getvalue()


# --------------------------------------------------------------------------
# Recontrôle après un changement de grille (spec §6.4).
# --------------------------------------------------------------------------


async def apres_changement_grille(
    session: AsyncSession,
    *,
    fournisseur_id: uuid.UUID,
    date_effet: date,
    cle_produit_modifiee: str | None = None,
) -> None:
    """Point d'accroche du recontrôle des bons après un import ou une
    saisie de prix (spec §6.4, tâche P7) : recontrôle les bons non
    archivés de `fournisseur_id` datés à partir de `date_effet`
    (`ingest.prix_bl.recontroler_bons`, chaque bon dans sa propre
    transaction -- un échec est journalisé et n'annule ni les autres bons
    ni l'écriture de la grille déjà commitée par l'appelant).

    Import différé (comme les autres imports différés de cette base de
    code, ex. `app.cli`) : `ingest.prix_bl` importe `prix_en_vigueur` d'ici,
    un import en tête de fichier créerait un cycle.

    `cle_produit_modifiee` (recontrôle des bons portant une alerte de prix
    ouverte sur ce produit précis, après une validation de prix -- spec
    §6.4) n'est pas encore câblé : la page Prix qui appelle « Valider ce
    prix » avec ce paramètre est la tâche P8, pas encore construite."""
    del cle_produit_modifiee

    from app.modules.ingest.prix_bl import recontroler_bons

    await recontroler_bons(session, fournisseur_id=fournisseur_id, depuis=date_effet)
