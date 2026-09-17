"""`base_joignable` : sonde bornée dans le temps (`SELECT 1`), sans jamais
laisser fuir de détail d'exception à l'appelant (décisions du contrôleur
T4).

Aucune fixture réelle : la base « joignable » utilisée ici est `bl_test`
(`TEST_DATABASE_URL`), déjà exigée par `tests/conftest.py` pour toute la
suite ; le port « injoignable » est un port TCP libre choisi au hasard sur
`127.0.0.1`, jamais en écoute.

Le port fermé échoue par `ECONNREFUSED` instantané : il ne prouve rien sur
la borne `timeout_s`. `test_base_joignable_faux_et_rapide_si_connexion_pendante`
couvre ce cas séparément avec un serveur TCP qui accepte la connexion sans
jamais répondre (relevé en revue de T4, tour 1).
"""

from __future__ import annotations

import socket
import time

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import base_joignable

pytestmark = pytest.mark.anyio


def _port_libre() -> int:
    """Port TCP libre sur `127.0.0.1` (personne n'écoute dessus)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.db
async def test_base_joignable_vrai_si_la_base_repond(url_base_test_prete: str) -> None:
    engine = create_async_engine(url_base_test_prete, poolclass=NullPool)

    try:
        assert await base_joignable(engine) is True
    finally:
        await engine.dispose()


@pytest.mark.db
async def test_base_joignable_faux_si_base_absente(url_base_test_prete: str) -> None:
    url = make_url(url_base_test_prete).set(database="bl_test_base_absente_inventee")
    engine = create_async_engine(url, poolclass=NullPool)

    try:
        assert await base_joignable(engine) is False
    finally:
        await engine.dispose()


@pytest.mark.db
async def test_base_joignable_faux_si_identifiants_invalides(
    url_base_test_prete: str,
) -> None:
    url = make_url(url_base_test_prete).set(
        password="mot-de-passe-invente-faux"  # noqa: S106 -- test, jamais un vrai secret
    )
    engine = create_async_engine(url, poolclass=NullPool)

    try:
        assert await base_joignable(engine) is False
    finally:
        await engine.dispose()


async def test_base_joignable_faux_et_rapide_si_port_ferme() -> None:
    port = _port_libre()
    engine = create_async_engine(
        f"postgresql+asyncpg://bl:x@127.0.0.1:{port}/bl", poolclass=NullPool
    )

    debut = time.monotonic()
    try:
        resultat = await base_joignable(engine)
    finally:
        await engine.dispose()
    duree = time.monotonic() - debut

    assert resultat is False
    assert duree < 3


async def test_base_joignable_faux_et_rapide_si_connexion_pendante(
    port_connexion_pendante: int,
) -> None:
    engine = create_async_engine(
        f"postgresql+asyncpg://bl:x@127.0.0.1:{port_connexion_pendante}/bl",
        poolclass=NullPool,
    )

    debut = time.monotonic()
    try:
        resultat = await base_joignable(engine, timeout_s=0.5)
    finally:
        await engine.dispose()
    duree = time.monotonic() - debut

    assert resultat is False
    assert duree < 1.5
