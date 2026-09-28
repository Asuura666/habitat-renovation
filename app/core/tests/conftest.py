"""Fixtures locales à `app/core/tests/` : `tests/conftest.py` ne s'applique
qu'aux tests situés sous `tests/`, donc ce dossier a besoin de son propre
backend anyio et de sa propre garantie que `bl_test` est prête. On réutilise
les fonctions pures de `tests/conftest.py` (pas les fixtures, invisibles ici)
pour ne pas dupliquer la logique de création/migration.
"""

from __future__ import annotations

import asyncio
import contextlib
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
    """URL de `bl_test`, garantie créée et migrée à `head`.

    Fixture **synchrone** à dessein : `preparer_base` appelle en interne
    `asyncio.run(...)`, qui échoue si une boucle asyncio tourne déjà (cas
    d'une fixture async, ou d'un appel direct depuis un test `anyio`).
    """
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
    testé (les dépendances FastAPI de `app.core.auth`) ouvre lui-même ses
    sessions via `app.state.sessions`."""
    return creer_sessionmaker(db_engine)


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session de test pour préparer/observer les données ; toutes les
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


@pytest.fixture
async def port_connexion_pendante() -> AsyncIterator[int]:
    """Port TCP qui accepte la connexion mais ne répond jamais.

    Contrairement à un port fermé (`ECONNREFUSED` instantané), c'est le seul
    moyen de prouver que `asyncio.timeout` coupe réellement une connexion qui
    pend (relevé en revue de T4, tour 1 : le test « port fermé » ne prouvait
    pas la borne de temps).

    Chaque connexion acceptée reste bloquée sur un `asyncio.Event` qui n'est
    jamais posé (jamais de lecture ni d'écriture) : le client ne reçoit donc
    jamais de réponse. Le `finally` annule explicitement les tâches de
    handler encore en vie, ce qui déclenche leur propre `finally` (fermeture
    du `writer`/transport) : on ne compte jamais sur le comportement du
    client (annulé par `asyncio.timeout`) pour fermer proprement sa moitié
    de la connexion, ce qui laissait le `writer` du serveur ouvert et
    produisait un `ResourceWarning: unclosed transport` (relevé en revue de
    T4, tour 2 — `serveur.close()`/`wait_closed()` ne ferment que le socket
    d'écoute, jamais les connexions déjà acceptées).
    """
    taches: list[asyncio.Task[None]] = []

    async def _handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    def _accepter(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        taches.append(asyncio.ensure_future(_handler(reader, writer)))

    serveur = await asyncio.start_server(_accepter, "127.0.0.1", 0)
    port: int = serveur.sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        serveur.close()
        await serveur.wait_closed()
        for tache in taches:
            tache.cancel()
        if taches:
            await asyncio.gather(*taches, return_exceptions=True)
