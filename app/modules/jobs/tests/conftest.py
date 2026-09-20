"""Fixtures DB locales aux tests des jobs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import Base, creer_sessionmaker
from tests.conftest import lire_test_database_url, preparer_base


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def url_base_test_prete() -> str:
    url = lire_test_database_url()
    preparer_base(url)
    return url


@pytest.fixture(scope="session")
def db_engine(url_base_test_prete: str) -> Iterator[AsyncEngine]:
    engine = create_async_engine(url_base_test_prete, poolclass=NullPool)
    yield engine

    async def fermer() -> None:
        await engine.dispose()

    asyncio.run(fermer())


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    sessions = creer_sessionmaker(db_engine)
    async with sessions() as session:
        yield session

    noms_tables = ", ".join(
        f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables)
    )
    async with db_engine.begin() as connexion:
        await connexion.execute(
            text(f"TRUNCATE {noms_tables} RESTART IDENTITY CASCADE")
        )
