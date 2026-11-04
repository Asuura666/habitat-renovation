"""Historique des prix d'un produit (lot 2 du 31/10/2026, B4).

« quand on clique sur le produit dans la grille, on peut voir tout
l'historique du produit ». Deux services :

- `importer_historique_prix` : lit une feuille d'historique d'un fichier de
  contrôle (`extract.historique_prix`) et range chaque ligne dans
  `prix_observe`. La clé du produit suit la règle de la grille
  (`normalize.prix.cle_produit`). Idempotent : une ligne identique (même
  produit, même date, même facture, même prix, même quantité) n'est pas
  réimportée. Ces prix ne vont **jamais** dans la grille.
- `historique_complet` : tout ce qu'on sait d'un produit d'un fournisseur,
  trié par date décroissante, 100 lignes au plus -- les versions de la
  grille (avec leur origine en français), les prix vus sur les bons et les
  factures du même fournisseur et les prix observés importés.

Limite connue (`docs/dette.md`) : les prix vus sur les bons et les factures
ne sont retrouvés que par la référence du produit (code lu égal à la
référence de la grille), jamais par le nom.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.extract.historique_prix import lire_historique_prix
from app.modules.ingest.grilles import FournisseurIntrouvable
from app.modules.ingest.models import (
    Document,
    Fournisseur,
    GrillePrix,
    Ligne,
    PrixObserve,
    Utilisateur,
)
from app.modules.normalize.prix import cle_produit, normaliser_reference
from app.modules.normalize.texte import normaliser_libelle

LIMITE_HISTORIQUE = 100

_TYPES_DOCUMENT = {"bl": "bon", "enlevement": "bon d'enlèvement", "facture": "facture"}


class FournisseurNonTrouve(Exception):
    """Aucun fournisseur ne porte ce nom (ni comme nom, ni comme alias)."""


class FournisseurAmbigu(Exception):
    """Plusieurs fournisseurs portent ce nom une fois normalisé."""


@dataclass(frozen=True)
class BilanImportHistorique:
    lues: int
    importees: int
    deja_presentes: int
    erreurs: int


async def trouver_fournisseur_par_nom(session: AsyncSession, nom: str) -> Fournisseur:
    """Le fournisseur de ce nom (insensible à la casse, aux accents et à la
    ponctuation), nom canonique ou alias. `FournisseurNonTrouve` s'il n'y en
    a aucun, `FournisseurAmbigu` s'il y en a plusieurs."""
    voulu = normaliser_libelle(nom)
    trouves = [
        fournisseur
        for fournisseur in (await session.execute(select(Fournisseur))).scalars()
        if voulu
        in {
            normaliser_libelle(fournisseur.nom),
            *(normaliser_libelle(alias) for alias in fournisseur.aliases or ()),
        }
    ]
    if not trouves:
        raise FournisseurNonTrouve(nom)
    if len(trouves) > 1:
        raise FournisseurAmbigu(nom)
    return trouves[0]


def _identite(
    cle: str, jour: date, piece: str | None, prix: Decimal, quantite: Decimal | None
) -> tuple[str, date, str | None, Decimal, Decimal | None]:
    return (cle, jour, piece, prix, quantite)


async def importer_historique_prix(
    session: AsyncSession,
    *,
    fournisseur_nom: str,
    contenu: bytes,
    feuille: str,
    source: str,
    simulation: bool = False,
) -> BilanImportHistorique:
    """Importe la feuille `feuille` du classeur `contenu` pour le fournisseur
    `fournisseur_nom`. Lève `FournisseurNonTrouve`/`FournisseurAmbigu`, et
    les erreurs de lecture de `extract.historique_prix`
    (`FichierGrilleInvalide`, `FeuilleIntrouvable`). En simulation, compte
    sans rien écrire."""
    fournisseur = await trouver_fournisseur_par_nom(session, fournisseur_nom)
    lu = lire_historique_prix(contenu, feuille)

    existantes = {
        _identite(
            ligne.cle_produit,
            ligne.date_observation,
            ligne.piece,
            ligne.prix_ht,
            ligne.quantite,
        )
        for ligne in (
            await session.execute(
                select(PrixObserve).where(PrixObserve.fournisseur_id == fournisseur.id)
            )
        ).scalars()
    }

    importees = 0
    deja = 0
    for ligne in lu.lignes:
        cle = cle_produit(ligne.reference, ligne.designation)
        identite = _identite(
            cle, ligne.date_observation, ligne.piece, ligne.prix_ht, ligne.quantite
        )
        if identite in existantes:
            deja += 1
            continue
        existantes.add(identite)
        importees += 1
        if not simulation:
            session.add(
                PrixObserve(
                    fournisseur_id=fournisseur.id,
                    cle_produit=cle,
                    reference=ligne.reference,
                    designation=ligne.designation,
                    unite_brut=ligne.unite_brut,
                    date_observation=ligne.date_observation,
                    prix_ht=ligne.prix_ht,
                    quantite=ligne.quantite,
                    piece=ligne.piece,
                    source_libelle=source,
                )
            )
    if not simulation:
        await session.commit()
    return BilanImportHistorique(
        lues=len(lu.lignes),
        importees=importees,
        deja_presentes=deja,
        erreurs=len(lu.erreurs),
    )


@dataclass(frozen=True)
class EntreeHistorique:
    """Une ligne de l'historique d'un produit. `type` : `grille` (version de
    la grille), `document` (prix vu sur un bon ou une facture) ou `observe`
    (prix importé d'un fichier de contrôle). `origine` est déjà lisible."""

    type: str
    date: date
    origine: str
    prix_ht: Decimal
    remise_pct: Decimal | None
    prix_net: Decimal | None
    unite: str | None
    quantite: Decimal | None
    numero_document: str | None
    document_id: uuid.UUID | None
    type_document: str | None


def _jour_paris(instant: object) -> date:
    return instant.astimezone(FUSEAU_PARIS).date()  # type: ignore[attr-defined,no-any-return]


def _origine_grille(
    version: GrillePrix, auteur: Utilisateur | None, document: Document | None
) -> str:
    if version.source == "import":
        origine = f"Fichier importé le {_jour_paris(version.created_at):%d/%m/%Y}"
    elif version.source == "validation":
        numero = document.numero if document is not None else None
        origine = (
            f"Validé depuis le bon n° {numero}" if numero else "Validé depuis un bon"
        )
    else:
        nom = (auteur.nom or auteur.email) if auteur is not None else None
        origine = f"Saisi par {nom}" if nom else "Saisi à l'écran"
    return f"Retiré de la grille · {origine}" if version.retire else origine


_RANG = {"grille": 0, "document": 1, "observe": 2}


async def historique_complet(
    session: AsyncSession, fournisseur_id: uuid.UUID, cle: str
) -> list[EntreeHistorique]:
    """Historique d'un produit (`cle` = clé de produit de la grille), de la
    date la plus récente à la plus ancienne, `LIMITE_HISTORIQUE` lignes au
    plus. Lève `FournisseurIntrouvable`. Un produit sans aucune ligne rend
    une liste vide."""
    if await session.get(Fournisseur, fournisseur_id) is None:
        raise FournisseurIntrouvable(str(fournisseur_id))

    entrees: list[EntreeHistorique] = []

    versions = (
        await session.execute(
            select(GrillePrix, Utilisateur, Document)
            .outerjoin(Utilisateur, Utilisateur.id == GrillePrix.auteur_id)
            .outerjoin(Document, Document.id == GrillePrix.document_id)
            .where(
                GrillePrix.fournisseur_id == fournisseur_id,
                GrillePrix.cle_produit == cle,
            )
            .order_by(GrillePrix.date_effet.desc(), GrillePrix.created_at.desc())
            .limit(LIMITE_HISTORIQUE)
        )
    ).all()
    reference: str | None = None
    for version, auteur, document in versions:
        if reference is None and version.reference:
            reference = version.reference
        entrees.append(
            EntreeHistorique(
                type="grille",
                date=version.date_effet,
                origine=_origine_grille(version, auteur, document),
                prix_ht=version.prix_ht,
                remise_pct=version.remise_pct,
                prix_net=version.prix_net,
                unite=version.unite_brut,
                quantite=None,
                numero_document=None,
                document_id=None,
                type_document=None,
            )
        )

    observes = (
        (
            await session.execute(
                select(PrixObserve)
                .where(
                    PrixObserve.fournisseur_id == fournisseur_id,
                    PrixObserve.cle_produit == cle,
                )
                .order_by(
                    PrixObserve.date_observation.desc(), PrixObserve.created_at.desc()
                )
                .limit(LIMITE_HISTORIQUE)
            )
        )
        .scalars()
        .all()
    )
    for observe in observes:
        if reference is None and observe.reference:
            reference = observe.reference
        entrees.append(
            EntreeHistorique(
                type="observe",
                date=observe.date_observation,
                origine=observe.source_libelle,
                prix_ht=observe.prix_ht,
                remise_pct=None,
                prix_net=None,
                unite=observe.unite_brut,
                quantite=observe.quantite,
                numero_document=observe.piece,
                document_id=None,
                type_document=None,
            )
        )

    # Prix vus sur les bons et factures : seulement par la référence (le
    # nom lu sur un bon n'est pas assez fiable pour affirmer que c'est le
    # même produit).
    reference_normalisee = (
        cle[4:] if cle.startswith("ref:") else normaliser_reference(reference)
    )
    if reference_normalisee:
        code_nettoye = func.regexp_replace(
            func.lower(Ligne.code_brut), "[^a-z0-9]", "", "g"
        )
        vus = (
            await session.execute(
                select(Ligne, Document)
                .join(Document, Document.id == Ligne.document_id)
                .where(
                    Document.fournisseur_id == fournisseur_id,
                    Document.statut != "archive",
                    Ligne.code_brut.is_not(None),
                    Ligne.pu_ht.is_not(None),
                    code_nettoye == reference_normalisee,
                )
                .order_by(Document.date_doc.desc().nulls_last())
                .limit(LIMITE_HISTORIQUE * 5)
            )
        ).all()
        for ligne, document in vus:
            if (
                ligne.pu_ht is None
                or normaliser_reference(ligne.code_brut) != reference_normalisee
            ):
                continue
            nature = _TYPES_DOCUMENT.get(document.type, "document")
            entrees.append(
                EntreeHistorique(
                    type="document",
                    date=document.date_doc or _jour_paris(document.created_at),
                    origine=(
                        f"Vu sur {'la' if document.type == 'facture' else 'le'} "
                        f"{nature} n° {document.numero}"
                        if document.numero
                        else f"Vu sur un document ({nature})"
                    ),
                    prix_ht=ligne.pu_ht,
                    remise_pct=ligne.remise_pct,
                    prix_net=None,
                    unite=ligne.unite_brut,
                    quantite=(
                        ligne.qte_livree
                        if ligne.qte_livree is not None
                        else ligne.qte_totale
                    ),
                    numero_document=document.numero,
                    document_id=document.id,
                    type_document=document.type,
                )
            )

    entrees.sort(key=lambda e: (-e.date.toordinal(), _RANG[e.type]))
    return entrees[:LIMITE_HISTORIQUE]
