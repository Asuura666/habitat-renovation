"""Fixtures locales à `app/core/tests/` : `tests/conftest.py` ne s'applique
qu'aux tests situés sous `tests/`, donc ce dossier a besoin de son propre
backend anyio et de sa propre garantie que `bl_test` est prête. On réutilise
les fonctions pures de `tests/conftest.py` (pas les fixtures, invisibles ici)
pour ne pas dupliquer la logique de création/migration.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest

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
