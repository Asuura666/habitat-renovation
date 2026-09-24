"""Point d'entrée FastAPI.

`get_settings()` est appelé au niveau du module, donc à l'import : une
variable d'environnement manquante fait échouer l'import (et donc le
démarrage d'uvicorn) avant qu'aucune route ne soit servie.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.auth import router as auth_router
from app.core.config import get_settings
from app.core.db import base_joignable, creer_engine, creer_sessionmaker
from app.core.front import monter_front
from app.core.origine import ControleOrigineMiddleware
from app.modules.api import router as api_router
from app.modules.ingest.router import router as ingest_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = creer_engine(settings.database_url)
    app.state.engine = engine
    app.state.sessions = creer_sessionmaker(engine)
    # Timeout explicite (minor reporté de la revue T6, corrigé en T6b) :
    # sans cela, httpx attend indéfiniment un appel qui ne répond jamais
    # (ex. Telegram inaccessible). 30 s au total, 10 s pour établir la
    # connexion ; l'appel OCR Mistral (plus long) surcharge ce timeout à
    # 60 s par requête (voir `ingest/mistral.ocr_document`).
    app.state.http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
    try:
        yield
    finally:
        await app.state.http.aclose()
        await engine.dispose()


# `/docs`/`/redoc`/`/openapi.json` exposent le schéma complet de l'API sans
# authentification : désactivés par défaut (`api_docs_actives`, optionnelle,
# défaut `False` -- voir `app.core.config.Settings`), à activer
# explicitement (`API_DOCS_ACTIVES=true`) si un besoin le justifie. Ne
# change rien à `web/package.json` (`api:schema`), qui appelle
# `app.openapi()` directement en Python plutôt que cette URL.
_docs_actives = settings.api_docs_actives
app = FastAPI(
    lifespan=lifespan,
    docs_url="/docs" if _docs_actives else None,
    redoc_url="/redoc" if _docs_actives else None,
    openapi_url="/openapi.json" if _docs_actives else None,
)
# Point 2 (vague finale du lot 2) : défense en profondeur CSRF sur `/api/*`
# (voir `app/core/origine.py`) — `/tg/webhook` n'est pas concerné.
app.add_middleware(ControleOrigineMiddleware)
app.include_router(ingest_router)
app.include_router(auth_router)
app.include_router(api_router)


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Vérifie que la base est joignable. Ne renvoie jamais de détail
    d'exception : uniquement `{"statut": "ok"/"ko", "base": "ok"/"injoignable"}`.
    """
    if await base_joignable(request.app.state.engine):
        return JSONResponse({"statut": "ok", "base": "ok"}, status_code=200)
    return JSONResponse({"statut": "ko", "base": "injoignable"}, status_code=503)


# Montage du front (L2-D16) : seulement si le build existe déjà (`web/dist`,
# copié par le Dockerfile multi-étage) — la suite de tests tourne sans lui.
# Placé après toutes les routes ci-dessus (et les routes `/docs`/`/redoc`/
# `/openapi.json` posées par `FastAPI(...)` plus haut, quand `api_docs_actives`
# les active) : le fallback `GET /{chemin:path}` de `monter_front` ne doit
# jamais leur être prioritaire. Quand elles sont désactivées, ces trois
# chemins restent bloqués : `_PREFIXES_RESERVES` d'`app.core.front` les
# renvoie en 404 plutôt que de laisser le fallback les servir comme l'app
# React.
_DOSSIER_FRONT = Path(__file__).resolve().parent.parent / "web" / "dist"
if _DOSSIER_FRONT.exists():
    monter_front(app, _DOSSIER_FRONT)
