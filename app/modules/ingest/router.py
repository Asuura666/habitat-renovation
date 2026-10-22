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
   et édition du message, tout dans `ingest/depot_telegram.py`).
6. Expéditeur sans identifiant Telegram -> `signaler_expediteur_inconnu`
   part en tâche de fond (notification de supervision, aucune écriture ni
   téléchargement) -> 200. Sinon `depot_telegram.rattacher_ou_creer_deposant`
   (décision d'Ilane du 02/10/2026, remplace la liste blanche stricte
   L2-D7) : compte actif retrouvé, ou créé au premier envoi ; compte
   désactivé -> `refuser_compte_desactive` en tâche de fond (supervision et
   réponse dans le groupe, aucune écriture ni téléchargement) -> 200.
7. Sinon, `traiter_fichier` part en tâche de fond (`BackgroundTasks`) -> 200
   (téléchargement, écriture, document, OCR Mistral, ligne de supervision
   puis réponse « reçu » avec numéro interne et boutons, L2-D9).

Le routeur reste mince : aucune règle métier, seulement cet enchaînement
(décision du contrôleur, L2-T2) — `ingest/depot_telegram.py` décide de tout
le reste (qui est rattaché, ce qui est écrit, ce qui est envoyé).

La messagerie de production est un `TelegramClient` construit sur le
`httpx.AsyncClient` du lifespan (`app.state.http`), fournie via une
dépendance FastAPI surchargeable dans les tests
(`app.dependency_overrides[get_messagerie]`). L'OCR de production
(`get_ocr`) est construit de la même façon, sur ce même client et sur
`Settings.mistral_api_key`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.modules.extract.bl import OPTIONS_OCR_BL
from app.modules.ingest.depot_telegram import (
    enregistrer_update,
    rattacher_ou_creer_deposant,
    refuser_compte_desactive,
    signaler_expediteur_inconnu,
    traiter_clic,
    traiter_fichier,
)
from app.modules.ingest.mistral import ocr_document
from app.modules.messaging.base import ClicBouton, Messagerie
from app.modules.messaging.telegram import TelegramClient, lire_update, secret_valide

router = APIRouter()

# L2-T4 : délai OCR dédié au dépôt d'une facture (`get_ocr_facture`), plus
# long que celui des photos avant T6 (60 s par défaut, `ocr_document`) — une
# facture de plusieurs pages peut prendre plus de temps à analyser (décision
# du contrôleur, borne haute du CDC : délai max 90 s).
_DELAI_OCR_FACTURE = httpx.Timeout(90.0)
# T6 : l'annotation structurée (`OPTIONS_OCR_BL`) et les scores de confiance
# par mot allongent l'analyse d'une photo de BL — même borne haute que pour
# une facture (décision du contrôleur).
# Publique (sans `_`, décision du contrôleur L3-T11) : `app.cli::rapport-ocr`
# réutilise cette même constante pour construire l'OCR réel de `--appeler-ocr`
# (mêmes options et délai que `get_ocr`, jamais un simple doublon de sa valeur).
DELAI_OCR_BL = httpx.Timeout(90.0)
# L3-T7 (L3-D16, décision du contrôleur) : confiance par page pour une
# facture (`extract.confiance.confiance_min_pages`, lu par
# `ingest/factures.py::deposer_facture`) — jamais l'annotation structurée ni
# les scores par mot d'`OPTIONS_OCR_BL`, réservés au BL (T6).
_OPTIONS_OCR_FACTURE: dict[str, Any] = {"confidence_scores_granularity": "page"}


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
    options: Mapping[str, Any] | None = None,
) -> Callable[[bytes, str], Awaitable[dict[str, Any]]]:
    """Construit la fonction OCR de production, sur le client HTTP du
    lifespan et la clé API de la configuration — partagée par `get_ocr`
    (photos, T6 : `OPTIONS_OCR_BL`, délai porté à 90 s) et `get_ocr_facture`
    (factures, L2-T4, délai porté à 90 s ; L3-T7 : `_OPTIONS_OCR_FACTURE`,
    confiance par page)."""
    http = request.app.state.http
    cle_api = settings.mistral_api_key.get_secret_value()

    async def _ocr(contenu: bytes, mime: str) -> dict[str, Any]:
        return await ocr_document(
            http, cle_api, contenu, mime, delai=delai, options=options
        )

    return _ocr


def get_ocr(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Callable[[bytes, str], Awaitable[dict[str, Any]]]:
    """OCR de production (T6b, complété T6) : appelle l'API Mistral OCR via
    le client HTTP du lifespan et la clé API de la configuration, avec
    `OPTIONS_OCR_BL` (annotation structurée + scores de confiance par mot,
    lus par `ingest/extraction_bl.py::enregistrer_extraction_bl`) et un délai
    porté à 90 s. Fonction injectée dans `traiter_fichier`, surchargeable
    dans les tests (`app.dependency_overrides[get_ocr]`) sans construire de
    client HTTP."""
    return _construire_ocr(
        request, settings, delai=DELAI_OCR_BL, options=OPTIONS_OCR_BL
    )


def get_ocr_facture(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> Callable[[bytes, str], Awaitable[dict[str, Any]]]:
    """OCR de production pour le dépôt d'une facture (L2-T4, délai porté à
    90 s ; L3-T7/L3-D16, `_OPTIONS_OCR_FACTURE` : confiance par page, lue
    par `ingest/factures.py::deposer_facture` via `extract.confiance
    .confiance_min_pages`). Utilisée par `app/modules/api/factures.py`,
    surchargeable dans les tests de la même façon que `get_ocr`."""
    return _construire_ocr(
        request, settings, delai=_DELAI_OCR_FACTURE, options=_OPTIONS_OCR_FACTURE
    )


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
        # édition du message) vit dans `ingest/depot_telegram.py::traiter_clic`.
        background_tasks.add_task(
            traiter_clic,
            entrant,
            messagerie,
            sessions,
            settings.telegram_chat_supervision_id,
        )
        return Response(status_code=200)

    if entrant.expediteur_id is None:
        background_tasks.add_task(
            signaler_expediteur_inconnu,
            entrant,
            messagerie,
            settings.telegram_chat_supervision_id,
        )
        return Response(status_code=200)

    # Décision d'Ilane du 02/10/2026 : le premier envoi d'un employé inconnu
    # crée son compte ; seul un compte désactivé est encore refusé.
    deposant = await rattacher_ou_creer_deposant(session, entrant)
    # FastAPI ne ferme la session de la requête qu'après les tâches de fond
    # (dépendance `yield`, vérifié avec FastAPI 0.141) : sans ce commit, la
    # transaction ouverte par la recherche de l'expéditeur garderait sa
    # connexion pendant toute la lecture du bon (≈ 30 s) et une rafale de
    # photos épuiserait le pool (incident du 07/10/2026 : 3 photos sur 16
    # perdues, `TimeoutError` à l'enregistrement).
    await session.commit()
    if deposant is None:
        background_tasks.add_task(
            refuser_compte_desactive,
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
