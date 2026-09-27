"""Fixtures locales à `app/modules/api/tests/` : `tests/conftest.py` ne
s'applique qu'aux tests situés sous `tests/`, donc ce dossier a besoin de son
propre backend anyio et de sa propre base de test prête (même schéma
`bl_test`, décision D13 : base injoignable = échec explicite, jamais skip).

Copie de `app/modules/ingest/tests/conftest.py` : chaque dossier de tests
d'un module a besoin de ses propres fixtures (pytest ne les partage pas
entre paquets frères), et `api` ne peut pas importer `ingest.tests` (ce
serait un import croisé au sens de `tests/test_frontieres.py`)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
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
    # `NullPool` : chaque test tourne dans sa propre boucle asyncio (plugin
    # anyio), un pool par défaut garderait des connexions asyncpg créées
    # dans une boucle déjà fermée (mêmes raisons que `tests/conftest.py`).
    engine = create_async_engine(url_base_test_prete, poolclass=NullPool)
    yield engine

    async def _fermer() -> None:
        await engine.dispose()

    asyncio.run(_fermer())


@pytest.fixture
def sessions_test(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fabrique de sessions branchée sur `bl_test`, utilisée là où le code
    testé (le routeur) ouvre lui-même ses sessions (`app.state.sessions`)."""
    return creer_sessionmaker(db_engine)


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session de test pour observer/préparer les données ; toutes les
    tables sont vidées après le test."""
    sessionmaker = creer_sessionmaker(db_engine)
    async with sessionmaker() as session:
        yield session

    noms_tables = ", ".join(
        f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables)
    )
    async with db_engine.begin() as connexion:
        # `grille_prix` (migration 0013) refuse tout TRUNCATE (historique
        # inaltérable, déclencheur `grille_prix_sans_truncate`) : désactivé
        # le temps de ce nettoyage de fin de test puis réactivé -- jamais
        # contourné par le code applicatif, seulement par ce nettoyage.
        await connexion.execute(text("ALTER TABLE grille_prix DISABLE TRIGGER ALL"))
        await connexion.execute(
            text(f"TRUNCATE {noms_tables} RESTART IDENTITY CASCADE")
        )
        await connexion.execute(text("ALTER TABLE grille_prix ENABLE TRIGGER ALL"))
