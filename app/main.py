"""Point d'entrée FastAPI.

`get_settings()` est appelé au niveau du module, donc à l'import : une
variable d'environnement manquante fait échouer l'import (et donc le
démarrage d'uvicorn) avant qu'aucune route ne soit servie.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import base_joignable, creer_engine, creer_sessionmaker

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = creer_engine(settings.database_url)
    app.state.engine = engine
    app.state.sessions = creer_sessionmaker(engine)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """Vérifie que la base est joignable. Ne renvoie jamais de détail
    d'exception : uniquement `{"statut": "ok"/"ko", "base": "ok"/"injoignable"}`.
    """
    if await base_joignable(request.app.state.engine):
        return JSONResponse({"statut": "ok", "base": "ok"}, status_code=200)
    return JSONResponse({"statut": "ko", "base": "injoignable"}, status_code=503)
