"""Synchronisation périodique des documents vers Drive (L5-T11)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fuseau import FUSEAU_PARIS
from app.modules.ingest.models import Chantier, Document, Fournisseur
from app.modules.jobs.drive import ClientDrive, normaliser_segment

_DELAI_SIGNAL = timedelta(hours=24)
Signaler = Callable[[str], Awaitable[None]]
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResultatSynchronisation:
    traites: int
    reussis: int
    echecs: int
    signales: int


def _segment_unique(valeur: str, identifiant: uuid.UUID) -> str:
    suffixe = str(identifiant)
    lisible = normaliser_segment(valeur)[: 100 - len(suffixe) - 1].rstrip("-._")
    return f"{lisible}-{suffixe}"


def _dossier(fournisseur: Fournisseur, document: Document) -> str:
    date_document = document.date_doc
    if date_document is None:
        date_document = document.created_at.astimezone(FUSEAU_PARIS).date()
    return "/".join(
        (
            "Fournisseurs",
            _segment_unique(fournisseur.nom, fournisseur.id),
            f"{date_document:%Y-%m}",
        )
    )


def _nom_fichier(document: Document, chantier: str | None) -> str:
    extension = Path(document.fichier_path).suffix.lower().lstrip(".") or "bin"
    numero = document.numero or str(document.numero_interne)
    chantier_affiche = chantier or document.chantier_brut or "sans-chantier"
    return (
        "_".join(
            (
                normaliser_segment(document.type),
                normaliser_segment(numero),
                normaliser_segment(chantier_affiche),
                str(document.id),
            )
        )
        + f".{normaliser_segment(extension)}"
    )


async def synchroniser_documents(
    session: AsyncSession,
    client: ClientDrive,
    *,
    limite: int,
    maintenant: datetime | None = None,
    signaler: Signaler | None = None,
) -> ResultatSynchronisation:
    """Téléverse les documents non synchronisés sous verrou de lot.

    Un document sans fournisseur résolu reste en attente : le chemin exigé
    commence par son fournisseur et ne doit pas figer un dossier « inconnu ».
    Le commit du lot conserve les verrous ``SKIP LOCKED`` pendant les envois ;
    un arrêt après téléversement reste rejouable car le client vérifie le nom
    distant avant tout nouvel envoi.

    Les signalements suivent une sémantique « au plus une fois » : leur date
    est validée en base avant l'appel externe. Une panne Telegram peut donc
    perdre une notification, mais ne provoque jamais de doublon au passage
    suivant.
    """

    if limite < 1:
        raise ValueError("La limite doit être positive")
    await session.execute(text("SELECT pg_advisory_xact_lock(127941, 511)"))
    instant = maintenant or datetime.now(UTC)
    selection = (
        select(Document, Fournisseur, Chantier.nom_canonique)
        .join(Fournisseur, Fournisseur.id == Document.fournisseur_id)
        .outerjoin(Chantier, Chantier.id == Document.chantier_id)
        .where(Document.drive_sync_le.is_(None))
    )
    nouveaux = [
        (document, fournisseur, chantier)
        for document, fournisseur, chantier in (
            await session.execute(
                selection.where(Document.drive_sync_tentative_le.is_(None))
                .order_by(Document.created_at, Document.id)
                .limit(limite)
                .with_for_update(skip_locked=True, of=Document)
            )
        ).all()
    ]
    reessais = [
        (document, fournisseur, chantier)
        for document, fournisseur, chantier in (
            await session.execute(
                selection.where(Document.drive_sync_tentative_le.is_not(None))
                .order_by(Document.drive_sync_tentative_le, Document.id)
                .limit(limite)
                .with_for_update(skip_locked=True, of=Document)
            )
        ).all()
    ]
    if limite == 1:
        prioritaire, secours = (
            (reessais, nouveaux) if instant.hour % 2 else (nouveaux, reessais)
        )
        lignes = (prioritaire or secours)[:1]
    else:
        lignes = []
        for index in range(limite):
            categorie = nouveaux if index % 2 == 0 else reessais
            position = index // 2
            if position < len(categorie):
                lignes.append(categorie[position])
        if len(lignes) < limite:
            deja_retenus = {document.id for document, _, _ in lignes}
            complement = nouveaux + reessais
            lignes.extend(
                ligne for ligne in complement if ligne[0].id not in deja_retenus
            )
            lignes = lignes[:limite]

    reussis = 0
    echecs = 0
    signales = 0
    notifications: list[str] = []
    for document, fournisseur, chantier in lignes:
        document.drive_sync_tentative_le = instant
        try:
            url = await client.televerser(
                Path(document.fichier_path),
                _dossier(fournisseur, document),
                _nom_fichier(document, chantier),
            )
        except Exception as exc:
            echecs += 1
            if document.drive_sync_echec_le is None:
                document.drive_sync_echec_le = instant
            document.drive_sync_erreur = type(exc).__name__
            if (
                signaler is not None
                and document.drive_sync_signale_le is None
                and document.drive_sync_echec_le <= instant - _DELAI_SIGNAL
            ):
                document.drive_sync_signale_le = instant
                notifications.append(
                    "Synchronisation Drive en échec depuis plus de 24 h "
                    f"pour le document interne {document.numero_interne}."
                )
        else:
            document.drive_url = url
            document.drive_sync_le = instant
            document.drive_sync_echec_le = None
            document.drive_sync_erreur = None
            document.drive_sync_signale_le = None
            reussis += 1

    await session.commit()
    if signaler is not None:
        for message in notifications:
            try:
                await signaler(message)
            except Exception as exc:
                _LOGGER.warning("Échec du signalement Drive (%s)", type(exc).__name__)
            else:
                signales += 1
    return ResultatSynchronisation(
        traites=len(lignes),
        reussis=reussis,
        echecs=echecs,
        signales=signales,
    )
