"""`ControleOrigineMiddleware` (vague finale du lot 2, point 2) : défense en
profondeur CSRF sur `/api/*`.

`FastAPI` isolé (jamais `app.main.app`), avec un faux `POST /api/echo` (même
préfixe que les vraies routes API) et un faux `POST /tg/webhook` (même
préfixe que le webhook Telegram, pour prouver qu'il n'est pas concerné). Les
scénarios avec de vraies routes (`/api/auth/login`, `/api/factures`) sont
couverts dans `test_auth.py`/`app/modules/api/tests/test_factures.py`.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from app.core.origine import ControleOrigineMiddleware

pytestmark = pytest.mark.anyio


def _app_test() -> FastAPI:
    app_test = FastAPI()
    app_test.add_middleware(ControleOrigineMiddleware)

    @app_test.post("/api/echo")
    async def _echo_api() -> dict[str, bool]:
        return {"ok": True}

    @app_test.get("/api/echo")
    async def _echo_api_get() -> dict[str, bool]:
        return {"ok": True}

    @app_test.post("/tg/webhook")
    async def _echo_webhook() -> dict[str, bool]:
        return {"ok": True}

    return app_test


async def _post(
    chemin: str, *, headers: dict[str, str] | None = None
) -> httpx.Response:
    transport = ASGITransport(app=_app_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(chemin, headers=headers or {})


async def _get(chemin: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = ASGITransport(app=_app_test())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(chemin, headers=headers or {})


async def test_sans_origin_ni_sec_fetch_site_accepte() -> None:
    """Client non-navigateur (curl, tests, appel serveur à serveur) :
    aucun des deux en-têtes -> accepté."""
    reponse = await _post("/api/echo")

    assert reponse.status_code == 200
    assert reponse.json() == {"ok": True}


async def test_origin_meme_origine_accepte() -> None:
    reponse = await _post("/api/echo", headers={"Origin": "http://test"})

    assert reponse.status_code == 200


async def test_origin_etrangere_refusee_403() -> None:
    reponse = await _post("/api/echo", headers={"Origin": "https://evil.example"})

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "Origine refusée."}


async def test_sec_fetch_site_cross_site_refuse_403() -> None:
    """Refusé même sans en-tête `Origin` (certains navigateurs n'envoient
    pas toujours `Origin` sur un formulaire simple, mais envoient déjà
    `Sec-Fetch-Site`)."""
    reponse = await _post("/api/echo", headers={"Sec-Fetch-Site": "cross-site"})

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "Origine refusée."}


async def test_sec_fetch_site_same_origin_accepte() -> None:
    reponse = await _post("/api/echo", headers={"Sec-Fetch-Site": "same-origin"})

    assert reponse.status_code == 200


async def test_methode_sure_get_non_concernee_meme_avec_origine_etrangere() -> None:
    """Seules les méthodes non sûres sont vérifiées : un `GET` passe toujours,
    quelle que soit l'origine."""
    reponse = await _get("/api/echo", headers={"Origin": "https://evil.example"})

    assert reponse.status_code == 200


async def test_webhook_telegram_non_concerne_meme_avec_origine_etrangere() -> None:
    """`/tg/webhook` est hors du préfixe `/api/` : jamais vérifié (appel
    serveur à serveur, protégé par le secret du webhook, pas par ce
    contrôle)."""
    reponse = await _post("/tg/webhook", headers={"Origin": "https://evil.example"})

    assert reponse.status_code == 200


async def test_webhook_telegram_non_concerne_avec_sec_fetch_site_cross_site() -> None:
    reponse = await _post("/tg/webhook", headers={"Sec-Fetch-Site": "cross-site"})

    assert reponse.status_code == 200
