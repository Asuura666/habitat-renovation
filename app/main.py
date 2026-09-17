"""Point d'entrée FastAPI.

`get_settings()` est appelé au niveau du module, donc à l'import : une
variable d'environnement manquante fait échouer l'import (et donc le
démarrage d'uvicorn) avant qu'aucune route ne soit servie.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import base_joignable, creer_engine, creer_sessionmaker
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


app = FastAPI(lifespan=lifespan)
app.include_router(ingest_router)


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Vérifie que la base est joignable. Ne renvoie jamais de détail
    d'exception : uniquement `{"statut": "ok"/"ko", "base": "ok"/"injoignable"}`.
    """
    if await base_joignable(request.app.state.engine):
        return JSONResponse({"statut": "ok", "base": "ok"}, status_code=200)
    return JSONResponse({"statut": "ko", "base": "injoignable"}, status_code=503)
