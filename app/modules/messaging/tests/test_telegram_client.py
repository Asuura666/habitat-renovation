"""`TelegramClient` : appels HTTP réels attendus (getFile, téléchargement,
sendMessage), via `httpx.MockTransport` (décision D12 : ni pytest-asyncio ni
respx). Le token utilisé ici est une valeur inventée, jamais un vrai
secret."""

from __future__ import annotations

import json

import httpx
import pytest

from app.modules.messaging.base import FichierEntrant
from app.modules.messaging.telegram import ErreurTelegram, TelegramClient

pytestmark = pytest.mark.anyio

TOKEN_INVENTE = "123456:AAA-token-de-test-invente"


def _fichier_photo(fichier_id: str = "grande-invente") -> FichierEntrant:
    return FichierEntrant(
        update_id=1,
        chat_id=10,
        message_id=5,
        expediteur_id=999,
        fichier_id=fichier_id,
        mime_type=None,
        nom_fichier=None,
        compresse=True,
    )


def _fichier_document_pdf(fichier_id: str = "doc-invente") -> FichierEntrant:
    return FichierEntrant(
        update_id=2,
        chat_id=11,
        message_id=6,
        expediteur_id=None,
        fichier_id=fichier_id,
        mime_type="application/pdf",
        nom_fichier="facture-invente.pdf",
        compresse=False,
    )


async def test_telecharger_appelle_getfile_puis_lurl_de_fichier_attendue() -> None:
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        if request.url.path.endswith("/getFile"):
            return httpx.Response(
                200, json={"ok": True, "result": {"file_path": "photos/file_1.jpg"}}
            )
        return httpx.Response(200, content=b"octets-invente-du-fichier")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(TOKEN_INVENTE, http)
        resultat = await client.telecharger(_fichier_photo("id-fichier-invente"))

    assert resultat.contenu == b"octets-invente-du-fichier"
    assert resultat.extension == "jpg"
    assert len(requetes) == 2
    assert requetes[0].url.path == f"/bot{TOKEN_INVENTE}/getFile"
    assert requetes[0].url.params["file_id"] == "id-fichier-invente"
    assert requetes[1].url.path == f"/file/bot{TOKEN_INVENTE}/photos/file_1.jpg"


async def test_telecharger_deduit_extension_du_type_mime_pour_un_document() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"file_path": "documents/file_2"}},
            )
        return httpx.Response(200, content=b"%PDF-invente")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(TOKEN_INVENTE, http)
        resultat = await client.telecharger(_fichier_document_pdf())

    assert resultat.extension == "pdf"
    assert resultat.contenu == b"%PDF-invente"


async def test_telecharger_leve_erreur_telegram_si_getfile_renvoie_ok_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(TOKEN_INVENTE, http)
        with pytest.raises(ErreurTelegram):
            await client.telecharger(_fichier_photo())


async def test_repondre_poste_sendmessage_avec_reply_parameters() -> None:
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(TOKEN_INVENTE, http)
        await client.repondre(chat_id=42, message_id=7, texte="reçu")

    assert len(requetes) == 1
    assert requetes[0].url.path == f"/bot{TOKEN_INVENTE}/sendMessage"
    corps = json.loads(requetes[0].content)
    assert corps == {
        "chat_id": 42,
        "text": "reçu",
        "reply_parameters": {"message_id": 7},
    }


async def test_envoyer_poste_sendmessage_sans_reply_parameters() -> None:
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(TOKEN_INVENTE, http)
        await client.envoyer(chat_id=-100123, texte="ligne de supervision inventee")

    assert len(requetes) == 1
    assert requetes[0].url.path == f"/bot{TOKEN_INVENTE}/sendMessage"
    corps = json.loads(requetes[0].content)
    assert corps == {"chat_id": -100123, "text": "ligne de supervision inventee"}


async def test_envoyer_leve_erreur_telegram_si_sendmessage_echoue() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(TOKEN_INVENTE, http)
        with pytest.raises(ErreurTelegram):
            await client.envoyer(chat_id=-100123, texte="ligne inventee")


async def test_erreur_http_pendant_envoyer_ne_contient_pas_le_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(TOKEN_INVENTE, http)
        with pytest.raises(ErreurTelegram) as exc_info:
            await client.envoyer(chat_id=-100123, texte="ligne inventee")

    assert TOKEN_INVENTE not in str(exc_info.value)
    assert "api.telegram.org" not in str(exc_info.value)


async def test_erreur_http_pendant_le_telechargement_ne_contient_pas_le_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(TOKEN_INVENTE, http)
        with pytest.raises(ErreurTelegram) as exc_info:
            await client.telecharger(_fichier_photo())

    assert TOKEN_INVENTE not in str(exc_info.value)
    assert "api.telegram.org" not in str(exc_info.value)


async def test_erreur_http_pendant_la_reponse_ne_contient_pas_le_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TelegramClient(TOKEN_INVENTE, http)
        with pytest.raises(ErreurTelegram) as exc_info:
            await client.repondre(chat_id=1, message_id=1, texte="reçu")

    assert TOKEN_INVENTE not in str(exc_info.value)
    assert "api.telegram.org" not in str(exc_info.value)
