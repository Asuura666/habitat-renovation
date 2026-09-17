"""`POST /tg/webhook` : unique point d'entrée Telegram (décision D10, le
routeur vit dans `ingest`, pas dans `messaging`, qui ne peut pas importer
`ingest`).

Déroulé (décisions du contrôleur T6, complété T6b) :
1. En-tête `X-Telegram-Bot-Api-Secret-Token` invalide ou absent -> 403.
2. `lire_update` renvoie `None` (rien à traiter) -> 200, rien n'est écrit.
3. `enregistrer_update` renvoie `False` (update déjà vu) -> 200.
4. Sinon, `traiter_fichier` part en tâche de fond (`BackgroundTasks`) -> 200
   (téléchargement, écriture, document, OCR Mistral puis réponse « reçu »).

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

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.modules.ingest.mistral import ocr_document
from app.modules.ingest.service import enregistrer_update, traiter_fichier
from app.modules.messaging.base import Messagerie
from app.modules.messaging.telegram import TelegramClient, lire_update, secret_valide

router = APIRouter()


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


def get_ocr(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Callable[[bytes, str], Awaitable[dict[str, Any]]]:
    """OCR de production (T6b) : appelle l'API Mistral OCR via le client
    HTTP du lifespan et la clé API de la configuration. Fonction injectée
    dans `traiter_fichier`, surchargeable dans les tests
    (`app.dependency_overrides[get_ocr]`) sans construire de client HTTP."""
    http = request.app.state.http
    cle_api = settings.mistral_api_key.get_secret_value()

    async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
        return await ocr_document(http, cle_api, contenu, mime)

    return _ocr


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

    nouveau = await enregistrer_update(session, entrant.update_id)
    if not nouveau:
        return Response(status_code=200)

    background_tasks.add_task(
        traiter_fichier, entrant, messagerie, sessions, settings.docs_dir, ocr
    )
    return Response(status_code=200)
