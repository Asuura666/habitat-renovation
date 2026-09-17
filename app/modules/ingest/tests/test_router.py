"""Tests de `POST /tg/webhook` (base de test réelle, `docs_dir` temporaire,
fausse `Messagerie`).

Chaque test construit un `FastAPI` dédié (jamais le cycle de vie ASGI de
`app/main.py`, qui n'est pas déclenché par `ASGITransport` — voir le
docstring de `app/core/tests/test_sante.py`) : ceci évite complètement de
muter puis restaurer l'état du singleton `app.main.app` entre les tests
(point de vigilance signalé par la revue de T4).

`CHAT_BL_TEST` (le `chat_id` par défaut de `_update_photo`) et
`CHAT_SUPERVISION_TEST` simulent `TELEGRAM_CHAT_BL_ID`/
`TELEGRAM_CHAT_SUPERVISION_ID` (L2-T2)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.modules.ingest.models import Document, TelegramUpdate, Utilisateur
from app.modules.ingest.router import get_messagerie, get_ocr, router
from app.modules.ingest.service import _MESSAGE_ECHEC_AGENT
from app.modules.messaging.base import FichierEntrant, FichierTelecharge

pytestmark = [pytest.mark.anyio, pytest.mark.db]

SECRET_TEST = "secret-webhook-invente-pour-les-tests"
TOKEN_TEST = "000000:jamais-appele-messagerie-surchargee"
CLE_MISTRAL_TEST = "cle-mistral-jamais-appelee-ocr-surcharge"
NUMERO_BL_TEST = "L209900000123"
CHAT_BL_TEST = 555
CHAT_SUPERVISION_TEST = 556
CHAT_ETRANGER_TEST = 777

_RE_LIGNE_SUPERVISION = re.compile(
    r"^Document n° (?P<numero_interne>\d+) · BL (?P<bl>.+) · fournisseur — · "
    r"chantier — · (?P<deposant>.+) · (?P<heure>\d{2}:\d{2}) · (?P<statut>\w+)$"
)


async def _ocr_test(contenu: bytes, mime: str) -> dict[str, Any]:
    """Faux OCR (T6b), surchargé via `get_ocr` : jamais de client HTTP réel
    dans ces tests de webhook. Renvoie un numéro de BL détectable pour que
    le document reste `recu` (comportement par défaut attendu par ces
    tests, centrés sur le webhook et non sur l'OCR lui-même — voir
    `app/modules/ingest/tests/test_service.py` pour les tests dédiés à
    l'OCR)."""
    return {"pages": [{"markdown": f"LIVRAISON N°{NUMERO_BL_TEST}"}]}


class MessagerieFactice:
    def __init__(self, *, echoue_telechargement: bool = False) -> None:
        self.echoue_telechargement = echoue_telechargement
        self.telechargements = 0
        self.reponses: list[tuple[int, int, str]] = []
        self.supervisions: list[tuple[int, str]] = []

    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge:
        self.telechargements += 1
        if self.echoue_telechargement:
            raise RuntimeError("échec factice de téléchargement")
        return FichierTelecharge(contenu=b"contenu-invente-photo", extension="jpg")

    async def repondre(self, chat_id: int, message_id: int, texte: str) -> None:
        self.reponses.append((chat_id, message_id, texte))

    async def envoyer(self, chat_id: int, texte: str) -> None:
        self.supervisions.append((chat_id, texte))


def _app_test(
    sessions: async_sessionmaker[AsyncSession],
    messagerie: MessagerieFactice,
    docs_dir: Path,
) -> FastAPI:
    """`FastAPI` isolé pour un test : le seul état partagé avec la
    production est le contrat des dépendances (`get_settings`,
    `get_messagerie`), toutes deux surchargées."""
    app_test = FastAPI()
    app_test.state.sessions = sessions
    app_test.include_router(router)
    app_test.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://inutilise:inutilise@localhost/inutilise",
        docs_dir=docs_dir,
        telegram_bot_token=SecretStr(TOKEN_TEST),
        telegram_webhook_secret=SecretStr(SECRET_TEST),
        telegram_chat_bl_id=CHAT_BL_TEST,
        telegram_chat_supervision_id=CHAT_SUPERVISION_TEST,
        mistral_api_key=SecretStr(CLE_MISTRAL_TEST),
    )
    app_test.dependency_overrides[get_messagerie] = lambda: messagerie
    app_test.dependency_overrides[get_ocr] = lambda: _ocr_test
    return app_test


async def _poster(
    app_test: FastAPI, update: dict[str, Any], secret: str | None
) -> httpx.Response:
    entetes: dict[str, str] = {}
    if secret is not None:
        entetes["X-Telegram-Bot-Api-Secret-Token"] = secret
    transport = ASGITransport(app=app_test)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/tg/webhook", json=update, headers=entetes)


def _update_photo(
    update_id: int,
    chat_id: int = CHAT_BL_TEST,
    message_id: int = 7,
    expediteur_id: int | None = 999,
    expediteur_nom: str | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": message_id,
        "chat": {"id": chat_id},
        "photo": [{"file_id": "petite-invente"}, {"file_id": "grande-invente"}],
    }
    if expediteur_id is not None:
        message["from"] = {"id": expediteur_id}
        if expediteur_nom is not None:
            message["from"]["username"] = expediteur_nom
    return {"update_id": update_id, "message": message}


async def _creer_utilisateur(
    db_session: AsyncSession,
    *,
    telegram_user_id: int,
    actif: bool = True,
    nom: str | None = "Agent Testeur",
) -> Utilisateur:
    utilisateur = Utilisateur(
        email=f"agent.{telegram_user_id}@example.invalid",
        role="agent",
        telegram_user_id=telegram_user_id,
        nom=nom,
        is_active=actif,
    )
    db_session.add(utilisateur)
    await db_session.commit()
    return utilisateur


def _parse_ligne_supervision(texte: str) -> re.Match[str]:
    match = _RE_LIGNE_SUPERVISION.match(texte)
    assert match is not None, f"ligne de supervision inattendue : {texte!r}"
    return match


async def test_secret_absent_renvoie_403_sans_rien_ecrire(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)

    reponse = await _poster(app_test, _update_photo(1), None)

    assert reponse.status_code == 403
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []


async def test_secret_invalide_renvoie_403_sans_rien_ecrire(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)

    reponse = await _poster(app_test, _update_photo(2), "mauvais-secret")

    assert reponse.status_code == 403
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []


async def test_chat_etranger_ignore_sans_rien_ecrire(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """L2-D6 : un chat différent de `TELEGRAM_CHAT_BL_ID` est ignoré, sans
    même le dédoublonnage (`telegram_update` reste vide)."""
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(3, chat_id=CHAT_ETRANGER_TEST)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.telechargements == 0
    assert messagerie.reponses == []
    assert messagerie.supervisions == []


async def test_photo_valide_cree_update_document_fichier_et_reponse(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=999)
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(42, chat_id=CHAT_BL_TEST, message_id=7, expediteur_id=999)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200

    updates = (await db_session.execute(select(TelegramUpdate))).scalars().all()
    assert [u.update_id for u in updates] == [42]

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    document = documents[0]
    assert (document.source, document.type, document.statut) == (
        "telegram",
        "bl",
        "recu",
    )
    assert document.telegram_message_id == 7
    assert document.photo_compressee is True

    fichiers = list(tmp_path.glob("*.jpg"))
    assert len(fichiers) == 1
    assert fichiers[0].read_bytes() == b"contenu-invente-photo"
    assert document.fichier_path == str(fichiers[0])

    assert messagerie.reponses == [(555, 7, "reçu")]

    # L2-D8 : une ligne de supervision par dépôt traité.
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_TEST
    match = _parse_ligne_supervision(texte)
    assert match["numero_interne"] == str(document.numero_interne)
    assert match["bl"] == NUMERO_BL_TEST
    assert match["deposant"] == "Agent Testeur"
    assert match["statut"] == "recu"


async def test_meme_update_id_envoye_deux_fois_ne_duplique_pas(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=999)
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(43)

    premiere = await _poster(app_test, update, SECRET_TEST)
    seconde = await _poster(app_test, update, SECRET_TEST)

    assert premiere.status_code == 200
    assert seconde.status_code == 200

    documents = (await db_session.execute(select(Document))).scalars().all()
    assert len(documents) == 1
    assert len(messagerie.reponses) == 1
    assert len(messagerie.supervisions) == 1


async def test_message_texte_ne_cree_rien_et_ne_repond_pas(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = {
        "update_id": 44,
        "message": {
            "message_id": 1,
            "chat": {"id": CHAT_BL_TEST},
            "text": "bonjour",
        },
    }

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.reponses == []
    assert messagerie.supervisions == []


async def test_expediteur_inconnu_ne_cree_rien_et_signale_en_supervision(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """L2-D7 : un expéditeur non rattaché ne crée aucun document, aucun
    téléchargement n'est tenté, et un unique message de supervision part
    (contenant l'identifiant Telegram) — un rejeu du même update n'en
    envoie pas un second (dédoublonnage acquis avant la résolution de
    l'expéditeur)."""
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(46, expediteur_id=123456, expediteur_nom="Inconnu")

    premiere = await _poster(app_test, update, SECRET_TEST)
    seconde = await _poster(app_test, update, SECRET_TEST)

    assert premiere.status_code == 200
    assert seconde.status_code == 200
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.telechargements == 0
    assert messagerie.reponses == []

    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_TEST
    assert "123456" in texte
    assert "Inconnu" in texte


async def test_expediteur_inactif_traite_comme_inconnu(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=888, actif=False)
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(47, expediteur_id=888)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.telechargements == 0
    assert messagerie.reponses == []
    assert len(messagerie.supervisions) == 1
    assert "888" in messagerie.supervisions[0][1]


async def test_telechargement_en_echec_signale_supervision_et_repond_echec_agent(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    await _creer_utilisateur(db_session, telegram_user_id=999)
    messagerie = MessagerieFactice(echoue_telechargement=True)
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(48)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []

    # Ruling R22 : réponse d'échec à l'agent, sans détail technique.
    assert messagerie.reponses == [(CHAT_BL_TEST, 7, _MESSAGE_ECHEC_AGENT)]

    # Message de supervision sans token ni contenu du fichier.
    assert len(messagerie.supervisions) == 1
    chat_id, texte = messagerie.supervisions[0]
    assert chat_id == CHAT_SUPERVISION_TEST
    assert TOKEN_TEST not in texte
    assert "contenu-invente-photo" not in texte

    # Le dédoublonnage a bien enregistré l'update malgré l'échec du
    # traitement en tâche de fond (décision du contrôleur : le webhook
    # marque l'update comme vu dès qu'il décide de le traiter).
    updates = (await db_session.execute(select(TelegramUpdate))).scalars().all()
    assert [u.update_id for u in updates] == [48]
