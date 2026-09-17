"""Tests de `POST /tg/webhook` (base de test réelle, `docs_dir` temporaire,
fausse `Messagerie`).

Chaque test construit un `FastAPI` dédié (jamais le cycle de vie ASGI de
`app/main.py`, qui n'est pas déclenché par `ASGITransport` — voir le
docstring de `app/core/tests/test_sante.py`) : ceci évite complètement de
muter puis restaurer l'état du singleton `app.main.app` entre les tests
(point de vigilance signalé par la revue de T4).
"""

from __future__ import annotations

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
from app.modules.ingest.router import get_messagerie, router
from app.modules.messaging.base import FichierEntrant, FichierTelecharge

pytestmark = [pytest.mark.anyio, pytest.mark.db]

SECRET_TEST = "secret-webhook-invente-pour-les-tests"
TOKEN_TEST = "000000:jamais-appele-messagerie-surchargee"


class MessagerieFactice:
    def __init__(self, *, echoue_telechargement: bool = False) -> None:
        self.echoue_telechargement = echoue_telechargement
        self.reponses: list[tuple[int, int, str]] = []

    async def telecharger(self, fichier: FichierEntrant) -> FichierTelecharge:
        if self.echoue_telechargement:
            raise RuntimeError("échec factice de téléchargement")
        return FichierTelecharge(contenu=b"contenu-invente-photo", extension="jpg")

    async def repondre(self, chat_id: int, message_id: int, texte: str) -> None:
        self.reponses.append((chat_id, message_id, texte))


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
    )
    app_test.dependency_overrides[get_messagerie] = lambda: messagerie
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
    chat_id: int = 555,
    message_id: int = 7,
    expediteur_id: int | None = 999,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "message_id": message_id,
        "chat": {"id": chat_id},
        "photo": [{"file_id": "petite-invente"}, {"file_id": "grande-invente"}],
    }
    if expediteur_id is not None:
        message["from"] = {"id": expediteur_id}
    return {"update_id": update_id, "message": message}


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


async def test_photo_valide_cree_update_document_fichier_et_reponse(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(42, chat_id=555, message_id=7, expediteur_id=999)

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

    fichiers = list(tmp_path.glob("*.jpg"))
    assert len(fichiers) == 1
    assert fichiers[0].read_bytes() == b"contenu-invente-photo"
    assert document.fichier_path == str(fichiers[0])

    assert messagerie.reponses == [(555, 7, "reçu")]


async def test_meme_update_id_envoye_deux_fois_ne_duplique_pas(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
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


async def test_message_texte_ne_cree_rien_et_ne_repond_pas(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = {
        "update_id": 44,
        "message": {"message_id": 1, "chat": {"id": 1}, "text": "bonjour"},
    }

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(TelegramUpdate))).scalars().all() == []
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert messagerie.reponses == []


async def test_deposant_id_rempli_si_utilisateur_connu(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    utilisateur = Utilisateur(
        email="agent.invente@example.invalid", role="agent", telegram_user_id=999
    )
    db_session.add(utilisateur)
    await db_session.commit()

    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(45, expediteur_id=999)

    await _poster(app_test, update, SECRET_TEST)

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.deposant_id == utilisateur.id


async def test_deposant_id_null_si_utilisateur_inconnu(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice()
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(46, expediteur_id=123456)

    await _poster(app_test, update, SECRET_TEST)

    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.deposant_id is None


async def test_telechargement_en_echec_necrit_ni_document_ni_fichier(
    db_session: AsyncSession,
    sessions_test: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    messagerie = MessagerieFactice(echoue_telechargement=True)
    app_test = _app_test(sessions_test, messagerie, tmp_path)
    update = _update_photo(47)

    reponse = await _poster(app_test, update, SECRET_TEST)

    assert reponse.status_code == 200
    assert (await db_session.execute(select(Document))).scalars().all() == []
    assert list(tmp_path.iterdir()) == []
    assert messagerie.reponses == []
    # Le dédoublonnage a bien enregistré l'update malgré l'échec du
    # traitement en tâche de fond (décision du contrôleur : le webhook
    # marque l'update comme vu dès qu'il décide de le traiter).
    updates = (await db_session.execute(select(TelegramUpdate))).scalars().all()
    assert [u.update_id for u in updates] == [47]
