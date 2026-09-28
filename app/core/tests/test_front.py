"""`monter_front` (L2-T6) : montage de `/assets` et renvoi d'`index.html`
pour toute route front, sauf les préfixes réservés à l'API et aux outils.

Faux dossier de build (`tmp_path`) : ces tests ne dépendent ni d'un vrai
`npm run build`, ni de la base de données. `FastAPI` isolé, jamais
`app.main.app` (voir le docstring de `test_sante.py`).
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from app.core.front import monter_front

pytestmark = pytest.mark.anyio

_INDEX_HTML = "<!doctype html><html><body>faux index</body></html>"
_ASSET_JS = "console.log('faux bundle');"


@pytest.fixture
def faux_dossier_build(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    dossier_assets = tmp_path / "assets"
    dossier_assets.mkdir()
    (dossier_assets / "x.js").write_text(_ASSET_JS, encoding="utf-8")
    return tmp_path


@pytest.fixture
def app_front(faux_dossier_build: Path) -> FastAPI:
    # docs/redoc/openapi désactivés : sans ça, `FastAPI()` les enregistre
    # elle-même sur `/docs`, `/redoc`, `/openapi.json` avant `monter_front`,
    # ce qui masquerait le test de leur exclusion explicite (ci-dessous) —
    # ces routes seraient de vraies 200, pas la preuve que le fallback les
    # exclut bien.
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/moi")
    async def _moi() -> dict[str, str]:
        return {"id": "faux"}

    monter_front(app, faux_dossier_build)
    return app


async def _get(app: FastAPI, chemin: str) -> httpx.Response:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(chemin)


async def test_racine_sert_index_html(app_front: FastAPI) -> None:
    reponse = await _get(app_front, "/")

    assert reponse.status_code == 200
    assert reponse.text == _INDEX_HTML
    assert "text/html" in reponse.headers["content-type"]


async def test_racine_index_html_pas_de_cache(app_front: FastAPI) -> None:
    """Point 3 (vague finale du lot 2) : `index.html` référence les fichiers
    hachés de `assets/` par leur nom — jamais mis en cache par le
    navigateur, contrairement aux fichiers sous `assets/` eux-mêmes."""
    reponse = await _get(app_front, "/")

    assert reponse.headers["cache-control"] == "no-cache"


async def test_route_front_inconnue_sert_aussi_index_html(app_front: FastAPI) -> None:
    """React Router décide côté client de la page affichée : `/factures`
    (ou toute autre route du front) doit recevoir le même `index.html`."""
    reponse = await _get(app_front, "/factures")

    assert reponse.status_code == 200
    assert reponse.text == _INDEX_HTML


async def test_route_front_inconnue_index_html_pas_de_cache(
    app_front: FastAPI,
) -> None:
    reponse = await _get(app_front, "/factures")

    assert reponse.headers["cache-control"] == "no-cache"


async def test_assets_sont_servis(app_front: FastAPI) -> None:
    reponse = await _get(app_front, "/assets/x.js")

    assert reponse.status_code == 200
    assert reponse.text == _ASSET_JS
    # Point 3 : contrairement à `index.html`, les fichiers hachés de
    # `assets/` restent cachables (aucun `Cache-Control: no-cache` ajouté).
    assert reponse.headers.get("cache-control") != "no-cache"


_CACHE_CONTROL_IMMUTABLE = "public, max-age=31536000, immutable"


async def test_asset_200_recoit_le_cache_control_immutable(
    app_front: FastAPI,
) -> None:
    """T6 : les fichiers hachés par Vite sous `/assets` sont cachables sans
    limite (nom unique par contenu) — `Cache-Control` long sur la réponse
    200, en plus de l'absence de `no-cache` déjà vérifiée ci-dessus."""
    reponse = await _get(app_front, "/assets/x.js")

    assert reponse.status_code == 200
    assert reponse.headers["cache-control"] == _CACHE_CONTROL_IMMUTABLE


async def test_asset_304_recoit_aussi_le_cache_control_immutable(
    app_front: FastAPI,
) -> None:
    """Requête conditionnelle (`If-None-Match` reprenant l'ETag reçu) : la
    réponse 304 de `StaticFiles` doit porter le même `Cache-Control`, sinon
    un navigateur qui revalide perdrait la directive `immutable` à chaque
    revalidation."""
    premiere_reponse = await _get(app_front, "/assets/x.js")
    etag = premiere_reponse.headers["etag"]

    transport = ASGITransport(app=app_front)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        reponse = await client.get("/assets/x.js", headers={"if-none-match": etag})

    assert reponse.status_code == 304
    assert reponse.headers["cache-control"] == _CACHE_CONTROL_IMMUTABLE


async def test_asset_inexistant_404_sans_cache_control_immutable(
    app_front: FastAPI,
) -> None:
    """Un fichier absent de `/assets` ne doit jamais recevoir le
    `Cache-Control` long : seuls les fichiers réellement servis (200/304)
    le portent."""
    reponse = await _get(app_front, "/assets/inexistant.js")

    assert reponse.status_code == 404
    assert reponse.headers.get("cache-control") != _CACHE_CONTROL_IMMUTABLE


async def test_route_api_inexistante_renvoie_404_json_pas_index(
    app_front: FastAPI,
) -> None:
    reponse = await _get(app_front, "/api/inexistant")

    assert reponse.status_code == 404
    assert reponse.headers["content-type"].startswith("application/json")
    assert reponse.text != _INDEX_HTML


@pytest.mark.parametrize(
    "chemin",
    ["/health", "/tg/webhook", "/docs", "/redoc", "/openapi.json"],
)
async def test_prefixes_reserves_ne_recoivent_jamais_index(
    app_front: FastAPI, chemin: str
) -> None:
    """Ces routes ne sont pas montées dans cet `app` isolé (pas de routeur
    `ingest`/`auth`/docs FastAPI désactivés) : elles doivent quand même
    tomber sur le 404 par défaut plutôt que sur `index.html`, preuve que le
    fallback front les exclut explicitement."""
    reponse = await _get(app_front, chemin)

    assert reponse.status_code == 404
    assert reponse.text != _INDEX_HTML


async def test_api_moi_deja_monte_reste_prioritaire_sur_lindex(
    app_front: FastAPI,
) -> None:
    reponse = await _get(app_front, "/api/moi")

    assert reponse.status_code == 200
    assert reponse.json() == {"id": "faux"}


async def test_dossier_sans_index_html_ne_monte_rien_et_journalise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Build incomplet ou mauvais dossier (pas d'`index.html`, même avec un
    dossier `assets`) : ne doit jamais planter `FileResponse` en 500 au
    premier appel — rien n'est monté, l'API reste servie normalement, et un
    avertissement est journalisé une fois."""
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "x.js").write_text(_ASSET_JS, encoding="utf-8")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/moi")
    async def _moi() -> dict[str, str]:
        return {"id": "faux"}

    with caplog.at_level(logging.WARNING, logger="app.core.front"):
        monter_front(app, tmp_path)

    assert any(
        "index.html" in enregistrement.message for enregistrement in caplog.records
    )

    reponse_racine = await _get(app, "/")
    assert reponse_racine.status_code == 404

    reponse_asset = await _get(app, "/assets/x.js")
    assert reponse_asset.status_code == 404

    reponse_api = await _get(app, "/api/moi")
    assert reponse_api.status_code == 200
    assert reponse_api.json() == {"id": "faux"}
