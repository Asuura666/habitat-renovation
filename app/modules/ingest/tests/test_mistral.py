"""Tests de `app/modules/ingest/mistral.py` (`httpx.MockTransport`, décision
D12 : ni pytest-asyncio ni respx). La clé API utilisée ici est une valeur
inventée, jamais un vrai secret (R17 : aucun appel réseau réel, aucun envoi
d'un document client)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.modules.ingest.mistral import ErreurOCR, ocr_document

pytestmark = pytest.mark.anyio

CLE_INVENTEE = "cle-api-mistral-inventee-pour-les-tests"
CONTENU_INVENTE = b"octets-invente-de-la-photo"


async def test_ocr_document_envoie_une_image_en_data_uri_base64_avec_auth() -> None:
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(200, json={"pages": [{"index": 0, "markdown": "texte"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        resultat = await ocr_document(http, CLE_INVENTEE, CONTENU_INVENTE, "image/jpeg")

    assert resultat == {"pages": [{"index": 0, "markdown": "texte"}]}
    assert len(requetes) == 1
    requete = requetes[0]
    assert str(requete.url) == "https://api.mistral.ai/v1/ocr"
    assert requete.headers["authorization"] == f"Bearer {CLE_INVENTEE}"

    corps = json.loads(requete.content)
    assert corps["model"] == "mistral-ocr-latest"
    assert corps["table_format"] == "markdown"
    assert corps["include_image_base64"] is False
    assert corps["document"]["type"] == "image_url"
    b64 = base64.b64encode(CONTENU_INVENTE).decode("ascii")
    assert corps["document"]["image_url"] == f"data:image/jpeg;base64,{b64}"


async def test_ocr_document_envoie_un_pdf_en_document_url() -> None:
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(200, json={"pages": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await ocr_document(http, CLE_INVENTEE, CONTENU_INVENTE, "application/pdf")

    corps = json.loads(requetes[0].content)
    assert corps["document"]["type"] == "document_url"
    b64 = base64.b64encode(CONTENU_INVENTE).decode("ascii")
    assert corps["document"]["document_url"] == f"data:application/pdf;base64,{b64}"


async def test_ocr_document_erreur_http_leve_erreur_ocr_sans_la_cle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "unauthorized"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ErreurOCR) as exc_info:
            await ocr_document(http, CLE_INVENTEE, CONTENU_INVENTE, "image/jpeg")

    assert CLE_INVENTEE not in str(exc_info.value)


async def test_ocr_document_erreur_connexion_leve_erreur_ocr_sans_la_cle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ErreurOCR) as exc_info:
            await ocr_document(http, CLE_INVENTEE, CONTENU_INVENTE, "image/jpeg")

    assert CLE_INVENTEE not in str(exc_info.value)
    assert "api.mistral.ai" not in str(exc_info.value)


async def test_ocr_document_corps_200_non_json_leve_erreur_ocr() -> None:
    """Correction tour 1/5 : un corps 200 illisible en JSON ne doit jamais
    lever une exception brute (`json.JSONDecodeError`) jusqu'à l'appelant."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"pas du json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ErreurOCR) as exc_info:
            await ocr_document(http, CLE_INVENTEE, CONTENU_INVENTE, "image/jpeg")

    assert CLE_INVENTEE not in str(exc_info.value)


async def test_ocr_document_corps_200_json_non_objet_leve_erreur_ocr() -> None:
    """Correction tour 1/5 : une réponse 200 dont le JSON n'est pas un objet
    (ex. une liste) doit lever `ErreurOCR`, jamais être renvoyée telle
    quelle (elle ferait planter `texte_ocr`/`detecter_numero_bl` en aval)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["pas", "un", "objet"])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(ErreurOCR) as exc_info:
            await ocr_document(http, CLE_INVENTEE, CONTENU_INVENTE, "image/jpeg")

    assert CLE_INVENTEE not in str(exc_info.value)
