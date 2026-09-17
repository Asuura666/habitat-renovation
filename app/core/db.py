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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    # `column_0_N_name` (et non `column_0_name`) : reprend TOUTES les
    # colonnes de la contrainte, pas seulement la première — deux
    # contraintes uniques d'une même table qui partageraient leur première
    # colonne (aucun cas actuellement, cf. `app/core/tests/test_db.py`)
    # produiraient sinon le même nom, qu'`alembic check` ne détecterait
    # jamais comme une dérive avant que Postgres ne refuse la création de la
    # seconde (collision de nom de contrainte). `ix` n'a pas besoin du même
    # traitement : `column_0_label` inclut déjà le nom de table, et aucun
    # index composite n'existe dans `app/modules/ingest/models.py` (revu à
    # cette occasion, tour de correction finale du lot 1).
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
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

    N'avale que les erreurs de connexion ou d'exécution, jamais les erreurs
    d'usage de SQLAlchemy (`ArgumentError`, `CompileError`, ...), qui
    signaleraient un bug de programmation :

    - `OSError` : refus de connexion (`ConnectionRefusedError`) ou dépassement
      de `timeout_s` (`asyncio.timeout` lève un `TimeoutError`, qui est une
      sous-classe d'`OSError` depuis PEP 3151 — pas besoin de le nommer à
      part).
    - `asyncpg.PostgresError` : le serveur répond mais refuse la connexion
      (base absente, identifiants invalides, ...). Ces erreurs surviennent
      pendant `engine.connect()`, avant que SQLAlchemy n'ait de connexion
      établie à envelopper : elles arrivent donc brutes, non enveloppées en
      `SQLAlchemyError`.
    - `sqlalchemy.exc.DBAPIError` : une fois la connexion établie, une panne
      pendant l'exécution (connexion coupée en cours de route, ...) est cette
      fois enveloppée par SQLAlchemy. `DBAPIError` couvre ses sous-classes
      (`OperationalError`, `InterfaceError`, ...) sans remonter jusqu'à
      `SQLAlchemyError`, trop large.

    Constats vérifiés empiriquement (asyncpg 0.31, SQLAlchemy 2.0.54) : port
    fermé -> `ConnectionRefusedError` brut ; base absente / identifiants
    invalides -> `asyncpg.exceptions.*Error` (sous-classes de `PostgresError`)
    bruts ; connexion coupée après établissement -> `sqlalchemy.exc.
    InterfaceError` (sous-classe de `DBAPIError`) ; connexion qui ne répond
    jamais -> `TimeoutError` porté par `asyncio.timeout`.
    """
    try:
        async with asyncio.timeout(timeout_s), engine.connect() as connexion:
            await connexion.execute(text("SELECT 1"))
    except (DBAPIError, PostgresError, OSError):
        return False
    return True
