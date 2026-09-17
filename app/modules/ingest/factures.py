"""Lecture et dépôt de facture : `lire_facture`/`blocs_avec_reception`/
`formater_blocs` (T7, livrable `python -m app.cli bl-non-recus`) et
`deposer_facture` (`POST /api/factures`, L2-T4).

Sous-module de `ingest`, issu du découpage de l'ancien `ingest/service.py`
(vague finale du lot 2, point 1 : simple déplacement de code, aucun
changement de comportement) : l'écriture atomique sur disque et le
`Deposant` partagés avec `ingest/depot_telegram.py` vivent désormais dans
`ingest/commun.py` ; la correspondance numéro de BL -> document reçu
(`documents_bl_par_numeros`, `_normaliser_numero`) et toute la lecture des
factures/documents déjà déposés vivent dans `ingest/lecture.py`.

Décision du contrôleur (révision après T5 requalifiée) : la facture est
toujours lue via l'OCR Mistral, jamais via pdfplumber (l'unique facture
disponible est un scan sans couche texte). `ocr` est injecté, même principe
que `depot_telegram.traiter_fichier` : en production, `app/cli.py` construit
`partial(ocr_document, http, cle_api)` à partir de `get_settings()` ; les
tests substituent une fonction qui renvoie une fixture ou une réponse
synthétique (R17 : aucun appel réel à Mistral).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.extract.confiance import confiance_min_pages
from app.modules.extract.facture import BlocBL, Facture, FactureIllisible, TypeLigne
from app.modules.extract.unikalo import analyser_facture_unikalo
from app.modules.extract.verification import (
    TOLERANCE_TOTAL_DEFAUT,
    motif_en_json,
    verifier_facture,
)
from app.modules.ingest.commun import Deposant, _ecrire_atomique, _supprimer_si_existe
from app.modules.ingest.extraction_bl import CLE_TOLERANCE_TOTAL_HT
from app.modules.ingest.lecture import _normaliser_numero, documents_bl_par_numeros
from app.modules.ingest.mistral import ErreurOCR
from app.modules.ingest.models import BlocFacture, Document, Fournisseur, Journal, Ligne
from app.modules.ingest.rapprochement import rapprocher_facture_sans_echec
from app.modules.ingest.referentiels import (
    lire_parametre_decimal,
    rattacher_article,
    resoudre_chantier,
)
from app.modules.normalize.article import proposer_article_facture


async def _lire_facture_ocr(
    contenu_pdf: bytes,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], Facture]:
    """Appelle l'OCR injecté sur `contenu_pdf` puis `analyser_facture_unikalo`
    sur sa réponse : aide interne partagée par `lire_facture` (T7, CLI
    `bl-non-recus`) et `deposer_facture` (L2-T4, décision du contrôleur), qui
    a en plus besoin de la réponse OCR brute pour `document.ocr_brut` — la
    signature publique de `lire_facture` ne change pas, elle jette juste la
    réponse brute. Ni `ErreurOCR` ni `FactureIllisible` ne sont interceptées
    ici : c'est à chaque appelant de décider quoi en faire (la CLI les
    propage telles quelles ; `deposer_facture` les traduit en erreurs
    typées HTTP)."""
    reponse = await ocr(contenu_pdf, "application/pdf")
    return reponse, analyser_facture_unikalo(reponse)


async def lire_facture(
    contenu_pdf: bytes,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
) -> Facture:
    """Lit une facture PDF via l'OCR injecté puis `analyser_facture_unikalo`.

    Lève `ErreurOCR` (`ingest/mistral.py`) si l'appel OCR échoue, ou
    `FactureIllisible` (`extract/facture.py`) si la réponse n'a pas la
    structure attendue d'une facture Unikalo. Ni l'une ni l'autre n'est
    interceptée ici : c'est à l'appelant (la CLI) de décider du code de
    sortie et du message.
    """
    _reponse, facture = await _lire_facture_ocr(contenu_pdf, ocr)
    return facture


@dataclass(frozen=True)
class BlocReception:
    """Un bloc « Concerne le B.L. » de la facture, avec l'indicateur
    « photo reçue » (livrable visible du lot 1, T7)."""

    numero_bl: str
    date_bl: date | None
    chantier_brut: str | None
    montant_ht: Decimal
    photo_recue: bool


async def blocs_avec_reception(
    session: AsyncSession, facture: Facture
) -> list[BlocReception]:
    """Une `BlocReception` par bloc de `facture`, dans l'ordre de la facture.

    « Photo reçue » (décisions du contrôleur T7, refactor L2-T5 sans
    changement de comportement) : correspondance factorisée dans
    `ingest.lecture.documents_bl_par_numeros`, réutilisée telle quelle."""
    documents_par_numero = await documents_bl_par_numeros(
        session, (bloc.numero_bl for bloc in facture.blocs)
    )

    return [
        BlocReception(
            numero_bl=bloc.numero_bl,
            date_bl=bloc.date_bl,
            chantier_brut=bloc.chantier_brut,
            montant_ht=bloc.montant_ht,
            photo_recue=_normaliser_numero(bloc.numero_bl) in documents_par_numero,
        )
        for bloc in facture.blocs
    ]


_ENTETE_TABLEAU = ("N° BL", "Date", "Chantier brut", "Montant HT", "Photo reçue")


def _formater_montant_fr(montant: Decimal) -> str:
    """Format français d'un montant : séparateur de milliers (espace),
    virgule décimale, toujours deux décimales (`Decimal("1234.5")` ->
    `"1 234,50"`). Le mini-langage de format de `Decimal` fait tout le
    travail (groupement, arrondi) : seuls les séparateurs sont substitués,
    jamais de conversion en `float`."""
    brut = f"{montant.quantize(Decimal('0.01')):,.2f}"
    return brut.replace(",", " ").replace(".", ",")


def _ligne_tableau(bloc: BlocReception) -> tuple[str, str, str, str, str]:
    return (
        bloc.numero_bl,
        bloc.date_bl.strftime("%d/%m/%Y") if bloc.date_bl is not None else "",
        bloc.chantier_brut or "",
        _formater_montant_fr(bloc.montant_ht),
        "oui" if bloc.photo_recue else "non",
    )


def formater_blocs(blocs: list[BlocReception]) -> str:
    """Tableau aligné (`N° BL | Date | Chantier brut | Montant HT | Photo
    reçue`), puis une ligne de synthèse `N blocs — X reçus — Y non reçus`
    (décision du contrôleur T7). Fonction pure : aucune base, aucun réseau."""
    lignes_donnees = [_ligne_tableau(bloc) for bloc in blocs]
    largeurs = [
        max(len(_ENTETE_TABLEAU[i]), *(len(ligne[i]) for ligne in lignes_donnees), 0)
        for i in range(len(_ENTETE_TABLEAU))
    ]

    def _formater_ligne(valeurs: tuple[str, ...]) -> str:
        return " | ".join(
            valeur.ljust(largeur)
            for valeur, largeur in zip(valeurs, largeurs, strict=True)
        ).rstrip()

    lignes = [_formater_ligne(_ENTETE_TABLEAU)]
    lignes.extend(_formater_ligne(ligne) for ligne in lignes_donnees)

    recus = sum(1 for bloc in blocs if bloc.photo_recue)
    non_recus = len(blocs) - recus
    lignes.append(f"{len(blocs)} blocs — {recus} reçus — {non_recus} non reçus")

    return "\n".join(lignes)


# --------------------------------------------------------------------------
# `deposer_facture` (L2-T4) : dépôt d'une facture PDF Unikalo via
# `POST /api/factures` (traité dans la requête, synchrone, L2-D11).
#
# Décisions du contrôleur :
# - Ordre : signature `%PDF-` (sinon `FichierInvalide`) -> OCR injecté
#   (`ErreurOCR` -> `LectureImpossible`) -> `analyser_facture_unikalo`
#   (`FactureIllisible` -> `FormatNonPrisEnCharge`) -> fournisseur
#   « Unikalo » get-or-create (normalisation SIRET/TVA réservée au lot 3,
#   un seul fournisseur nommé exactement « Unikalo » fait foi pour
#   l'instant) -> doublon `(fournisseur_id, numero)` parmi les documents de
#   type `facture` (`FactureEnDouble(original_id)`) -> écriture atomique du
#   fichier (`<uuid>.pdf`, réutilise `_ecrire_atomique`/`_supprimer_si_existe`
#   d'`ingest/commun.py`) -> insertions (`document`, `bloc_facture`, `ligne`,
#   `journal`) dans une seule transaction.
# - En cas d'échec d'insertion (y compris une `IntegrityError` d'unicité :
#   course entre deux dépôts concurrents du même fournisseur/numéro, la
#   vérification applicative ci-dessus n'étant pas atomique), le fichier
#   déjà écrit est supprimé et la transaction est annulée. Une
#   `IntegrityError` est retraduite en `FactureEnDouble` (409 aussi) en
#   requêtant à nouveau l'original après le `rollback`.
# - `commentaire` d'un `bloc_facture` : lignes `COMMENTAIRE` du bloc jointes
#   par `\n`, `NULL` s'il n'y en a aucune.
# - `ligne` : mapping direct des champs de `LigneFacture` (designation ->
#   `article_brut`, code_article -> `code_brut`, unite -> `unite_brut`,
#   `type_ligne.value`, `ordre` inchangé).
#
# Correction (revue L2-T4, Ruling L2-R5, constat mineur) :
# - L'écriture disque (`_ecrire_atomique`) est protégée comme dans
#   `depot_telegram.traiter_fichier` : un `OSError` (ex. disque plein)
#   nettoie le fichier temporaire déjà écrit et est retraduit en
#   `EcritureImpossible`, jamais laissé remonter brut (le routeur la traduit
#   en 500 neutre).
#
# L3-T7 (L3-D16, comble Ruling L2-R5) :
# - `confiance_min` = `extract.confiance.confiance_min_pages(reponse_ocr)`
#   (plus petit `minimum_page_confidence_score` des pages, options
#   `get_ocr_facture`/`router.py` : confiance par page, pas par mot).
# - Seule règle de contrôle d'une facture au lot 3 : `verifier_facture`
#   (somme des blocs vs `total_ht`, même tolérance que pour un BL —
#   `CLE_TOLERANCE_TOTAL_HT`, nommée dans `ingest/extraction_bl.py`,
#   réutilisée ici, décision du contrôleur) -> `document.statut`
#   (`a_verifier` si au moins un motif) et `document.motifs`.
# - Chantier de chaque bloc dont `chantier_brut` n'est pas vide, article de
#   chaque ligne `ARTICLE` avec un code : mêmes fonctions que pour un BL
#   (`ingest/referentiels.py::resoudre_chantier`/`rattacher_article`) —
#   jamais pour une ligne `eco`/`commentaire`. Aucune ligne de journal
#   supplémentaire par alias ou article : `nb_demandes_alias`/`nb_articles`
#   dans le journal `facture_deposee` suffisent (décision du contrôleur).
#
# Hors périmètre du lot 2 (Ruling L2-R5, décision du contrôleur, voir
# `docs/dette.md`) :
# - Un avoir Unikalo (CDC §4.2 « facture ou d'avoir ») serait aujourd'hui
#   typé `facture` comme n'importe quel dépôt (aucun exemple disponible pour
#   distinguer les deux formats) — question posée à Ilane
#   (`docs/plan-lot-2.md` §3, Q5).
# --------------------------------------------------------------------------


_SIGNATURE_PDF = b"%PDF-"
_NOM_FOURNISSEUR_UNIKALO = "Unikalo"


class FichierInvalide(Exception):
    """Le contenu envoyé n'a pas la signature d'un PDF (`%PDF-`)."""


class LectureImpossible(Exception):
    """Échec de l'appel OCR pour lire la facture (`ErreurOCR`)."""


class FormatNonPrisEnCharge(Exception):
    """La réponse OCR n'a pas la structure d'une facture Unikalo reconnue
    (`FactureIllisible`)."""


class EcritureImpossible(Exception):
    """Échec de l'écriture du fichier sur disque (`OSError`, ex. disque
    plein) — le fichier temporaire éventuellement écrit est nettoyé avant
    que cette exception ne soit levée."""


class FactureEnDouble(Exception):
    """Une facture du même fournisseur avec le même numéro est déjà déposée."""

    def __init__(self, original_id: uuid.UUID) -> None:
        super().__init__("facture déjà déposée")
        self.original_id = original_id


@dataclass(frozen=True)
class FactureDeposee:
    """Résultat d'un dépôt réussi, tout ce dont le routeur a besoin pour sa
    réponse 201 (`{"id", "numero", "nb_blocs"}`)."""

    id: uuid.UUID
    numero: str
    nb_blocs: int


async def _fournisseur_unikalo(session: AsyncSession) -> Fournisseur:
    """Fournisseur « Unikalo », créé s'il n'existe pas encore (décision du
    contrôleur : la normalisation SIRET/TVA n'arrive qu'au lot 3, un seul
    fournisseur nommé exactement « Unikalo » fait foi pour l'instant)."""
    resultat = await session.execute(
        select(Fournisseur).where(Fournisseur.nom == _NOM_FOURNISSEUR_UNIKALO)
    )
    fournisseur = resultat.scalar_one_or_none()
    if fournisseur is not None:
        return fournisseur
    fournisseur = Fournisseur(nom=_NOM_FOURNISSEUR_UNIKALO)
    session.add(fournisseur)
    await session.flush()
    return fournisseur


async def _facture_en_double(
    session: AsyncSession, fournisseur_id: uuid.UUID, numero: str
) -> uuid.UUID | None:
    """`id` du document `facture` existant pour ce fournisseur et ce numéro,
    `None` si aucun. Un seul point de vérité, réutilisé aussi pour retrouver
    l'original après une `IntegrityError` d'unicité (course entre deux
    dépôts)."""
    resultat = await session.execute(
        select(Document.id).where(
            Document.type == "facture",
            Document.fournisseur_id == fournisseur_id,
            Document.numero == numero,
        )
    )
    return resultat.scalar_one_or_none()


def _commentaire_bloc(bloc: BlocBL) -> str | None:
    commentaires = bloc.commentaires
    return "\n".join(commentaires) if commentaires else None


async def deposer_facture(
    session: AsyncSession,
    contenu: bytes,
    deposant: Deposant,
    docs_dir: Path,
    ocr: Callable[[bytes, str], Awaitable[dict[str, Any]]],
) -> FactureDeposee:
    """Dépose une facture PDF Unikalo : lecture, fournisseur, doublon,
    contrôle, résolution chantier/article, stockage et insertions dans une
    seule transaction (L2-T4, contrôle et normalisation L3-T7).

    Lève `FichierInvalide` (pas un PDF), `LectureImpossible` (échec de
    l'OCR), `FormatNonPrisEnCharge` (facture non reconnue comme Unikalo),
    `EcritureImpossible` (échec de l'écriture disque) ou
    `FactureEnDouble(original_id)` (même fournisseur, même numéro, déjà
    déposé) — le routeur (`app/modules/api/factures.py`) traduit chacune en
    code HTTP. Aucun fichier n'est stocké et rien n'est inséré en base tant
    que la facture n'est pas entièrement lue et validée.
    """
    if contenu[: len(_SIGNATURE_PDF)] != _SIGNATURE_PDF:
        raise FichierInvalide("Le fichier n'est pas un PDF.")

    try:
        reponse_ocr, facture = await _lire_facture_ocr(contenu, ocr)
    except ErreurOCR as exc:
        raise LectureImpossible("Lecture de la facture impossible, réessayez.") from exc
    except FactureIllisible as exc:
        raise FormatNonPrisEnCharge(
            "Format de facture non pris en charge "
            "(seules les factures Unikalo sont reconnues)."
        ) from exc

    fournisseur = await _fournisseur_unikalo(session)
    # Capturé tout de suite : un `rollback()` plus bas expirerait cet objet
    # (inconditionnellement, indépendamment d'`expire_on_commit`) — relire
    # `fournisseur.id` après coup lèverait `MissingGreenlet` (accès implicite
    # hors contexte async). Même prudence que `depot_telegram.traiter_fichier`
    # pour `document.id`/`numero_interne`, capturés avant tout risque de
    # rollback.
    fournisseur_id = fournisseur.id

    original_id = await _facture_en_double(session, fournisseur_id, facture.numero)
    if original_id is not None:
        raise FactureEnDouble(original_id)

    # L3-T7 (L3-D16) : confiance par page et seule règle de contrôle d'une
    # facture au lot 3 (somme des blocs vs total HT) — calculées avant le
    # stockage, sur `facture`/`reponse_ocr` déjà lus, jamais recalculées.
    confiance_min = confiance_min_pages(reponse_ocr)
    tolerance = await lire_parametre_decimal(
        session, CLE_TOLERANCE_TOTAL_HT, TOLERANCE_TOTAL_DEFAUT
    )
    motifs = list(verifier_facture(facture, tolerance=tolerance))
    statut = "a_verifier" if motifs else "recu"

    identifiant = uuid.uuid4()
    chemin_final = (docs_dir / f"{identifiant}.pdf").absolute()
    chemin_temporaire = (docs_dir / f"{identifiant}.pdf.tmp").absolute()
    try:
        await asyncio.to_thread(
            _ecrire_atomique, docs_dir, chemin_temporaire, chemin_final, contenu
        )
    except OSError as exc:
        # Correction (Ruling L2-R5, constat mineur) : même protection que
        # `traiter_fichier` — le `.tmp` éventuellement écrit ne doit jamais
        # rester orphelin, et l'`OSError` brute (chemins disque) ne doit
        # jamais remonter telle quelle jusqu'au routeur.
        await asyncio.to_thread(_supprimer_si_existe, chemin_temporaire)
        raise EcritureImpossible("Enregistrement impossible, réessayez.") from exc

    try:
        document = Document(
            type="facture",
            source="upload",
            statut=statut,
            fichier_path=str(chemin_final),
            fournisseur_id=fournisseur_id,
            numero=facture.numero,
            date_doc=facture.date_facture,
            total_ht=facture.total_ht,
            deposant_id=deposant.id,
            ocr_brut=reponse_ocr,
            confiance_min=confiance_min,
            motifs=[motif_en_json(m) for m in motifs],
        )
        session.add(document)
        await session.flush()
        document_id = document.id

        nb_demandes_alias = 0
        articles_rattaches: set[uuid.UUID] = set()

        for position, bloc in enumerate(facture.blocs):
            # L3-T7 (décision du contrôleur) : résolution seulement pour un
            # bloc dont le chantier brut n'est pas vide (`resoudre_chantier`
            # gère déjà un brut vide, mais l'appel est alors superflu et ne
            # compterait jamais comme une demande d'alias).
            chantier_id: uuid.UUID | None = None
            if bloc.chantier_brut:
                resolution_chantier = await resoudre_chantier(
                    session, fournisseur_id, bloc.chantier_brut
                )
                chantier_id = resolution_chantier.chantier_id
                if resolution_chantier.demande_creee:
                    nb_demandes_alias += 1

            bloc_facture = BlocFacture(
                facture_id=document_id,
                # Position sur la facture (constat T5, voir le commentaire de
                # `BlocFacture.ordre` dans `ingest/models.py`) : `created_at`
                # ne peut pas en tenir lieu, tous les blocs d'une même
                # facture étant insérés dans la même transaction.
                ordre=position,
                numero_bl=bloc.numero_bl,
                date_bl=bloc.date_bl,
                numero_commande=bloc.numero_commande,
                chantier_brut=bloc.chantier_brut,
                chantier_id=chantier_id,
                commentaire=_commentaire_bloc(bloc),
            )
            session.add(bloc_facture)
            await session.flush()
            bloc_id = bloc_facture.id

            for ligne in bloc.lignes:
                # L3-T7 (décision du contrôleur) : seulement une ligne
                # `ARTICLE` avec un code (L3-D9 : une éco-participation ou un
                # commentaire ne rattache jamais un article).
                article_id: uuid.UUID | None = None
                if ligne.type_ligne is TypeLigne.ARTICLE and ligne.code_article:
                    proposition = proposer_article_facture(
                        ligne.code_article,
                        ligne.designation,
                        ligne.qte_livree,
                        ligne.qte_totale,
                    )
                    article_id = await rattacher_article(
                        session, fournisseur_id, proposition
                    )
                    if article_id is not None:
                        articles_rattaches.add(article_id)

                session.add(
                    Ligne(
                        document_id=document_id,
                        bloc_id=bloc_id,
                        article_brut=ligne.designation,
                        code_brut=ligne.code_article,
                        article_id=article_id,
                        unite_brut=ligne.unite,
                        qte_livree=ligne.qte_livree,
                        qte_totale=ligne.qte_totale,
                        pu_ht=ligne.pu_ht,
                        pu_cdt=ligne.pu_cdt,
                        remise_pct=ligne.remise_pct,
                        montant_ht=ligne.montant_ht,
                        tva=ligne.tva,
                        type_ligne=ligne.type_ligne.value,
                        ordre=ligne.ordre,
                    )
                )

        session.add(
            Journal(
                utilisateur_id=deposant.id,
                action="facture_deposee",
                cible_table="document",
                cible_id=str(document_id),
                avant=None,
                apres={
                    "numero": facture.numero,
                    "fournisseur_id": str(fournisseur_id),
                    "total_ht": str(facture.total_ht),
                    "nb_blocs": len(facture.blocs),
                    "statut": statut,
                    "motifs": [m.code.value for m in motifs],
                    "nb_demandes_alias": nb_demandes_alias,
                    "nb_articles": len(articles_rattaches),
                },
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await asyncio.to_thread(_supprimer_si_existe, chemin_final)
        original_id_apres_course = await _facture_en_double(
            session, fournisseur_id, facture.numero
        )
        if original_id_apres_course is None:
            raise
        raise FactureEnDouble(original_id_apres_course) from None
    except Exception:
        await session.rollback()
        await asyncio.to_thread(_supprimer_si_existe, chemin_final)
        raise

    # L4-T7 (décision du contrôleur) : rapprochement déclenché juste après
    # le dépôt, encapsulé (`rapprocher_facture_sans_echec`) — un échec du
    # rapprochement ne doit jamais faire échouer le dépôt, déjà commité.
    await rapprocher_facture_sans_echec(session, document_id)

    return FactureDeposee(
        id=document_id, numero=facture.numero, nb_blocs=len(facture.blocs)
    )
