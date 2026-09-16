"""Base déclarative SQLAlchemy et fabriques d'engine / session async.

Convention de nommage explicite sur `Base.metadata` : les contraintes
(clés primaires, étrangères, uniques, `CHECK`) reçoivent un nom stable et
prévisible, condition pour que `alembic check` ne détecte jamais de dérive
entre les modèles et la base (un nom généré différemment d'une exécution à
l'autre serait vu comme une dérive).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from asyncpg import PostgresError
from fastapi import Request
from sqlalchemy import MetaData, text
from sqlalchemy.exc import SQLAlchemyError
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


async def base_joignable(engine: AsyncEngine, timeout_s: float = 2.0) -> bool:
    """`True` si `engine` peut exécuter `SELECT 1` en moins de `timeout_s` s.

    N'avale que les erreurs de connexion, SQL ou timeout
    (`sqlalchemy.exc.SQLAlchemyError`, `asyncpg.PostgresError`, `OSError`,
    `TimeoutError`) : un refus de connexion ou une base absente arrivent en
    `asyncpg`/`OSError` bruts (avant que SQLAlchemy n'ait de connexion à
    envelopper), une erreur SQL arrive en `SQLAlchemyError`. Toute autre
    exception remonte, pour ne jamais masquer un bug de programmation
    derrière un simple `False`.
    """
    try:
        async with asyncio.timeout(timeout_s), engine.connect() as connexion:
            await connexion.execute(text("SELECT 1"))
    except (SQLAlchemyError, PostgresError, OSError, TimeoutError):
        return False
    return True
