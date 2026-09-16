"""Base déclarative SQLAlchemy et fabriques d'engine / session async.

Convention de nommage explicite sur `Base.metadata` : les contraintes
(clés primaires, étrangères, uniques, `CHECK`) reçoivent un nom stable et
prévisible, condition pour que `alembic check` ne détecte jamais de dérive
entre les modèles et la base (un nom généré différemment d'une exécution à
l'autre serait vu comme une dérive).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base déclarative commune à tous les modèles ORM du projet."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def creer_engine(url: str) -> AsyncEngine:
    """Crée l'`AsyncEngine` SQLAlchemy pour l'URL donnée."""
    return create_async_engine(url)


def creer_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Crée la fabrique de sessions async liée à `engine`."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI : ouvre une session depuis `request.app.state.sessions`."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with sessionmaker() as session:
        yield session
