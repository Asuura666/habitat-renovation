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


async def test_ocr_document_delai_personnalise_remplace_le_delai_par_defaut() -> None:
    """L2-T4 : `delai` optionnel, utilisé par `get_ocr_facture` (délai de
    90 s pour une facture) sans changer le comportement par défaut (photos,
    `get_ocr`, délai omis)."""
    delais_recus: list[httpx.Timeout | float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"pages": []})

    class _ClientEspion(httpx.AsyncClient):
        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            delais_recus.append(kwargs.get("timeout"))  # type: ignore[arg-type]
            return await super().post(*args, **kwargs)  # type: ignore[arg-type]

    delai_facture = httpx.Timeout(90.0)
    async with _ClientEspion(transport=httpx.MockTransport(handler)) as http:
        await ocr_document(
            http,
            CLE_INVENTEE,
            CONTENU_INVENTE,
            "application/pdf",
            delai=delai_facture,
        )

    assert delais_recus == [delai_facture]


async def test_ocr_document_sans_delai_utilise_le_delai_par_defaut() -> None:
    delais_recus: list[httpx.Timeout | float | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"pages": []})

    class _ClientEspion(httpx.AsyncClient):
        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            delais_recus.append(kwargs.get("timeout"))  # type: ignore[arg-type]
            return await super().post(*args, **kwargs)  # type: ignore[arg-type]

    async with _ClientEspion(transport=httpx.MockTransport(handler)) as http:
        await ocr_document(http, CLE_INVENTEE, CONTENU_INVENTE, "image/jpeg")

    assert delais_recus == [httpx.Timeout(60.0)]


async def test_ocr_document_options_fusionnees_dans_le_corps() -> None:
    """T6 : les options passées sont fusionnées dans le corps envoyé."""
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(200, json={"pages": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await ocr_document(
            http,
            CLE_INVENTEE,
            CONTENU_INVENTE,
            "image/jpeg",
            options={
                "confidence_scores_granularity": "word",
                "document_annotation_prompt": "consigne-inventee",
            },
        )

    corps = json.loads(requetes[0].content)
    assert corps["confidence_scores_granularity"] == "word"
    assert corps["document_annotation_prompt"] == "consigne-inventee"
    assert corps["model"] == "mistral-ocr-latest"


async def test_ocr_document_options_ne_peuvent_pas_ecraser_les_cles_imposees() -> None:
    """Les clés imposées (`model`, `document`, `table_format`,
    `include_image_base64`) gagnent toujours sur `options`, même si
    l'appelant tente de les fournir lui-même."""
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(200, json={"pages": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await ocr_document(
            http,
            CLE_INVENTEE,
            CONTENU_INVENTE,
            "image/jpeg",
            options={
                "model": "modele-invente-ne-doit-pas-gagner",
                "table_format": "html",
                "include_image_base64": True,
            },
        )

    corps = json.loads(requetes[0].content)
    assert corps["model"] == "mistral-ocr-latest"
    assert corps["table_format"] == "markdown"
    assert corps["include_image_base64"] is False
    assert corps["document"]["type"] == "image_url"


async def test_ocr_document_sans_options_corps_inchange() -> None:
    """`options=None` (comportement par défaut) : le corps ne change pas par
    rapport au comportement d'avant T6."""
    requetes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requetes.append(request)
        return httpx.Response(200, json={"pages": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await ocr_document(http, CLE_INVENTEE, CONTENU_INVENTE, "image/jpeg")

    corps = json.loads(requetes[0].content)
    assert set(corps.keys()) == {
        "model",
        "document",
        "table_format",
        "include_image_base64",
    }


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
