"""`base_joignable` : sonde bornée dans le temps (`SELECT 1`), sans jamais
laisser fuir de détail d'exception à l'appelant (décisions du contrôleur
T4).

Aucune fixture réelle : la base « joignable » utilisée ici est `bl_test`
(`TEST_DATABASE_URL`), déjà exigée par `tests/conftest.py` pour toute la
suite ; le port « injoignable » est un port TCP libre choisi au hasard sur
`127.0.0.1`, jamais en écoute.
"""

from __future__ import annotations

import socket
import time

import pytest
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
