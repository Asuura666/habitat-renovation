"""Point d'entrée FastAPI.

`get_settings()` est appelé au niveau du module, donc à l'import : une
variable d'environnement manquante fait échouer l'import (et donc le
démarrage d'uvicorn) avant qu'aucune route ne soit servie.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import creer_engine, creer_sessionmaker

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
