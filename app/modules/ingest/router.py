"""`POST /tg/webhook` : unique point d'entrée Telegram (décision D10, le
routeur vit dans `ingest`, pas dans `messaging`, qui ne peut pas importer
`ingest`).

Déroulé (décisions du contrôleur T6, complété T6b, puis L2-T2, L2-T3) :
1. En-tête `X-Telegram-Bot-Api-Secret-Token` invalide ou absent -> 403.
2. `lire_update` renvoie `None` (rien à traiter) -> 200, rien n'est écrit.
3. `chat_id` différent de `Settings.telegram_chat_bl_id` (L2-D6) -> 200,
   rien n'est écrit (même le dédoublonnage est sauté) — s'applique aussi à
   un `ClicBouton` (L2-T3) : `chat_id` est un champ commun aux deux formes
   renvoyées par `lire_update`.
4. `enregistrer_update` renvoie `False` (update déjà vu) -> 200 (dédoublonne
   aussi le rejeu d'un `callback_query`, même mécanisme que pour un fichier).
5. `lire_update` a renvoyé un `ClicBouton` (L2-T3) : `traiter_clic` part en
   tâche de fond -> 200 (autorisation, mise à jour atomique, journal, accusé
   et édition du message, tout dans `ingest/service.py`).
6. `service.utilisateur_rattache` (liste blanche, L2-D7) : expéditeur non
   rattaché (absent ou compte inactif) -> `signaler_expediteur_inconnu` part
   en tâche de fond (notification de supervision, aucune écriture ni
   téléchargement) -> 200.
7. Sinon, `traiter_fichier` part en tâche de fond (`BackgroundTasks`) -> 200
   (téléchargement, écriture, document, OCR Mistral, ligne de supervision
   puis réponse « reçu » avec numéro interne et boutons, L2-D9).

Le routeur reste mince : aucune règle métier, seulement cet enchaînement
(décision du contrôleur, L2-T2) — `ingest/service.py` décide de tout le
reste (qui est rattaché, ce qui est écrit, ce qui est envoyé).

La messagerie de production est un `TelegramClient` construit sur le
`httpx.AsyncClient` du lifespan (`app.state.http`), fournie via une
dépendance FastAPI surchargeable dans les tests
(`app.dependency_overrides[get_messagerie]`). L'OCR de production
(`get_ocr`) est construit de la même façon, sur ce même client et sur
`Settings.mistral_api_key`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.modules.ingest.mistral import ocr_document
from app.modules.ingest.service import (
    enregistrer_update,
    signaler_expediteur_inconnu,
    traiter_clic,
    traiter_fichier,
    utilisateur_rattache,
)
from app.modules.messaging.base import ClicBouton, Messagerie
from app.modules.messaging.telegram import TelegramClient, lire_update, secret_valide

router = APIRouter()

# L2-T4 : délai OCR dédié au dépôt d'une facture (`get_ocr_facture`), plus
# long que celui des photos (60 s par défaut, `ocr_document`) — une facture
# de plusieurs pages peut prendre plus de temps à analyser (décision du
# contrôleur, borne haute du CDC : délai max 90 s).
_DELAI_OCR_FACTURE = httpx.Timeout(90.0)


def get_messagerie(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Messagerie:
    """Messagerie de production : `TelegramClient` sur le client HTTP du
    lifespan de l'application (`app.state.http`, ouvert/fermé dans
    `app/main.py`)."""
    return TelegramClient(
        token=settings.telegram_bot_token.get_secret_value(),
        http=request.app.state.http,
    )


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    """Fabrique de sessions du lifespan, pour que `traiter_fichier` ouvre sa
    propre session (la session de la requête est fermée avant que la tâche
    de fond ne s'exécute)."""
    sessions: async_sessionmaker[AsyncSession] = request.app.state.sessions
    return sessions


def _construire_ocr(
    request: Request,
    settings: Settings,
    *,
    delai: httpx.Timeout | None = None,
) -> Callable[[bytes, str], Awaitable[dict[str, Any]]]:
    """Construit la fonction OCR de production, sur le client HTTP du
    lifespan et la clé API de la configuration — partagée par `get_ocr`
    (photos, délai par défaut de `ocr_document`) et `get_ocr_facture`
    (factures, L2-T4, délai porté à 90 s)."""
    http = request.app.state.http
    cle_api = settings.mistral_api_key.get_secret_value()

    async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
        return await ocr_document(http, cle_api, contenu, mime, delai=delai)

    return _ocr


def get_ocr(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Callable[[bytes, str], Awaitable[dict[str, Any]]]:
    """OCR de production (T6b) : appelle l'API Mistral OCR via le client
    HTTP du lifespan et la clé API de la configuration. Fonction injectée
    dans `traiter_fichier`, surchargeable dans les tests
    (`app.dependency_overrides[get_ocr]`) sans construire de client HTTP."""
    return _construire_ocr(request, settings)


def get_ocr_facture(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Callable[[bytes, str], Awaitable[dict[str, Any]]]:
    """OCR de production pour le dépôt d'une facture (L2-T4, décision du
    contrôleur) : même construction que `get_ocr`, délai porté à 90 s.
    Utilisée par `app/modules/api/factures.py`, surchargeable dans les
    tests de la même façon que `get_ocr`."""
    return _construire_ocr(request, settings, delai=_DELAI_OCR_FACTURE)


@router.post("/tg/webhook")
async def webhook_telegram(
    update: Annotated[dict[str, Any], Body()],
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    messagerie: Annotated[Messagerie, Depends(get_messagerie)],
    sessions: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    ocr: Annotated[Callable[[bytes, str], Awaitable[dict[str, Any]]], Depends(get_ocr)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> Response:
    if not secret_valide(
        x_telegram_bot_api_secret_token,
        settings.telegram_webhook_secret.get_secret_value(),
    ):
        return Response(status_code=403)

    entrant = lire_update(update)
    if entrant is None:
        return Response(status_code=200)

    if entrant.chat_id != settings.telegram_chat_bl_id:
        # L2-D6 : seul le groupe BL configuré est traité, tout autre chat
        # est ignoré sans rien écrire (ni dédoublonnage, ni document).
        return Response(status_code=200)

    nouveau = await enregistrer_update(session, entrant.update_id)
    if not nouveau:
        return Response(status_code=200)

    if isinstance(entrant, ClicBouton):
        # L2-T3 : clic sur un des deux boutons de confirmation. Toute la
        # logique (autorisation, mise à jour atomique, journal, accusé et
        # édition du message) vit dans `ingest/service.py::traiter_clic`.
        background_tasks.add_task(
            traiter_clic,
            entrant,
            messagerie,
            sessions,
            settings.telegram_chat_supervision_id,
        )
        return Response(status_code=200)

    deposant = await utilisateur_rattache(session, entrant.expediteur_id)
    if deposant is None:
        background_tasks.add_task(
            signaler_expediteur_inconnu,
            entrant,
            messagerie,
            settings.telegram_chat_supervision_id,
        )
        return Response(status_code=200)

    background_tasks.add_task(
        traiter_fichier,
        entrant,
        messagerie,
        sessions,
        settings.docs_dir,
        ocr,
        deposant,
        settings.telegram_chat_supervision_id,
    )
    return Response(status_code=200)
