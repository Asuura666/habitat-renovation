"""Orchestration de l'ingestion (D10) : `ingest` est le seul module métier
autorisé à importer un autre module métier (`messaging`), garde vérifiée par
`tests/test_frontieres.py`.

Deux responsabilités pour T6 :
- `enregistrer_update` : dédoublonnage des webhooks Telegram
  (`INSERT ... ON CONFLICT DO NOTHING` sur la clé primaire `update_id` de
  `telegram_update` — atomique côté base, donc sûr même si deux requêtes
  concurrentes portent le même `update_id`) ;
- `traiter_fichier` : téléchargement, écriture atomique sur disque puis
  enregistrement du `document` (décisions du contrôleur T6).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.ingest.models import Document, TelegramUpdate, Utilisateur
from app.modules.messaging.base import FichierEntrant, Messagerie

logger = logging.getLogger(__name__)


def _journaliser_echec(etape: str, update_id: int, exc: Exception) -> None:
    """Ne journalise jamais le token, le contenu d'un fichier ni le nom de
    fichier d'origine : uniquement l'`update_id` et le type de l'exception."""
    logger.error(
        "échec ingest (%s) pour update_id=%s : %s",
        etape,
        update_id,
        type(exc).__name__,
    )


async def enregistrer_update(session: AsyncSession, update_id: int) -> bool:
    """Enregistre `update_id` dans `telegram_update`.

    Renvoie `True` s'il s'agit d'un nouvel update (à traiter), `False` s'il
    a déjà été vu (webhook Telegram redélivré). `ON CONFLICT DO NOTHING`
    rend l'opération atomique au niveau de la base : deux requêtes
    concurrentes pour le même `update_id` ne peuvent jamais toutes les deux
    obtenir `True`.
    """
    resultat = await session.execute(
        insert(TelegramUpdate)
        .values(update_id=update_id)
        .on_conflict_do_nothing(index_elements=[TelegramUpdate.update_id])
        .returning(TelegramUpdate.update_id)
    )
    await session.commit()
    return resultat.scalar_one_or_none() is not None


async def _resoudre_deposant(
    session: AsyncSession, telegram_user_id: int | None
) -> uuid.UUID | None:
    """`deposant_id` selon la décision D15 : rempli si `telegram_user_id`
    correspond à un `utilisateur` connu, `None` sinon (pas de whitelist au
    lot 1)."""
    if telegram_user_id is None:
        return None
    resultat = await session.execute(
        select(Utilisateur.id).where(Utilisateur.telegram_user_id == telegram_user_id)
    )
    return resultat.scalar_one_or_none()


def _supprimer_si_existe(chemin: Path) -> None:
    chemin.unlink(missing_ok=True)


def _ecrire_atomique(
    docs_dir: Path, chemin_temporaire: Path, chemin_final: Path, contenu: bytes
) -> None:
    """Écriture atomique (décision du contrôleur T6) : fichier temporaire
    dans `docs_dir`, rempli, puis `os.replace` (rename atomique sur un même
    système de fichiers). Fonction synchrone, exécutée hors de la boucle
    asyncio via `asyncio.to_thread` (I/O disque bloquante)."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    chemin_temporaire.write_bytes(contenu)
    os.replace(chemin_temporaire, chemin_final)


async def traiter_fichier(
    entrant: FichierEntrant,
    messagerie: Messagerie,
    sessions: async_sessionmaker[AsyncSession],
    docs_dir: Path,
) -> None:
    """Télécharge le fichier, l'écrit sous `docs_dir/<uuid4>.<ext>`, insère
    le `document` correspondant puis répond « reçu ».

    En cas d'erreur à n'importe quelle étape, aucun document n'est inséré et
    aucun fichier partiel ne reste dans `docs_dir` (nettoyage explicite à
    chaque étape). Ouvre sa propre session (la session de la requête HTTP
    est déjà fermée quand cette tâche de fond s'exécute).
    """
    try:
        fichier = await messagerie.telecharger(entrant)
    except Exception as exc:
        # Toute erreur de téléchargement est journalisée puis avalée : la
        # tâche de fond n'a personne à qui remonter l'exception.
        _journaliser_echec("téléchargement", entrant.update_id, exc)
        return

    identifiant = uuid.uuid4()
    # `.absolute()` (pas `.resolve()`, qui ferait un accès disque pour
    # résoudre les liens symboliques) : garantit un `fichier_path` absolu
    # même si `docs_dir` était configuré en relatif, sans I/O bloquant ici.
    chemin_final = (docs_dir / f"{identifiant}.{fichier.extension}").absolute()
    chemin_temporaire = (docs_dir / f"{identifiant}.{fichier.extension}.tmp").absolute()

    try:
        await asyncio.to_thread(
            _ecrire_atomique, docs_dir, chemin_temporaire, chemin_final, fichier.contenu
        )
    except OSError as exc:
        await asyncio.to_thread(_supprimer_si_existe, chemin_temporaire)
        _journaliser_echec("écriture fichier", entrant.update_id, exc)
        return

    try:
        async with sessions() as session:
            deposant_id = await _resoudre_deposant(session, entrant.expediteur_id)
            session.add(
                Document(
                    type="bl",
                    source="telegram",
                    statut="recu",
                    fichier_path=str(chemin_final),
                    telegram_message_id=entrant.message_id,
                    deposant_id=deposant_id,
                )
            )
            await session.commit()
    except Exception as exc:
        # Le fichier est déjà écrit sur disque : il ne doit pas rester seul
        # (sans document associé) si l'enregistrement en base échoue.
        await asyncio.to_thread(_supprimer_si_existe, chemin_final)
        _journaliser_echec("enregistrement document", entrant.update_id, exc)
        return

    try:
        await messagerie.repondre(entrant.chat_id, entrant.message_id, "reçu")
    except Exception as exc:
        # Le document est déjà enregistré : on journalise sans revenir en
        # arrière (dédoublonnage déjà acquis, pas de nouvelle tentative).
        _journaliser_echec("réponse", entrant.update_id, exc)
