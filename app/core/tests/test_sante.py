"""`GET /health` : 200 si la base répond, 503 sinon, jamais de détail
d'exception dans le corps (décisions du contrôleur T4).

L'app n'est jamais démarrée via son cycle de vie ASGI (`ASGITransport` ne
déclenche pas le `lifespan` de `app/main.py`) : chaque test pose directement
`app.state.engine`, via `monkeypatch.setattr(..., raising=False)` plutôt
qu'une affectation directe, pour que l'attribut soit restauré (ou effacé s'il
n'existait pas encore) à la fin du test. `app.main.app` est un singleton
partagé par tout le process pytest : une affectation directe sans
restauration ferait fuir l'engine « port fermé »/« connexion pendante » d'un
test vers le suivant qui importerait `app.main.app` (relevé en revue de T4,
tour 1).
"""

from __future__ import annotations

import socket
import time

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.main import app

pytestmark = pytest.mark.anyio


def _port_libre() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _appeler_health() -> httpx.Response:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/health")


@pytest.mark.db
async def test_health_renvoie_200_quand_la_base_repond(
    url_base_test_prete: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_async_engine(url_base_test_prete, poolclass=NullPool)
    monkeypatch.setattr(app.state, "engine", engine, raising=False)

    try:
        reponse = await _appeler_health()
    finally:
        await engine.dispose()

    assert reponse.status_code == 200
    assert reponse.json() == {"statut": "ok", "base": "ok"}


async def test_health_renvoie_503_sous_3_secondes_sans_detail_si_port_ferme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _port_libre()
    engine = create_async_engine(
        f"postgresql+asyncpg://bl:x@127.0.0.1:{port}/bl", poolclass=NullPool
    )
    monkeypatch.setattr(app.state, "engine", engine, raising=False)

    debut = time.monotonic()
    try:
        reponse = await _appeler_health()
    finally:
        await engine.dispose()
    duree = time.monotonic() - debut

    assert duree < 3
    assert reponse.status_code == 503
    assert reponse.json() == {"statut": "ko", "base": "injoignable"}
    assert "Traceback" not in reponse.text
    assert str(port) not in reponse.text


async def test_health_renvoie_503_sous_3_secondes_si_connexion_pendante(
    port_connexion_pendante: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le port fermé ci-dessus échoue par `ECONNREFUSED` instantané : il ne
    prouve pas que la route respecte la borne de temps de `base_joignable`.
    Ce test utilise un serveur qui accepte la connexion sans jamais répondre.
    """
    engine = create_async_engine(
        f"postgresql+asyncpg://bl:x@127.0.0.1:{port_connexion_pendante}/bl",
        poolclass=NullPool,
    )
    monkeypatch.setattr(app.state, "engine", engine, raising=False)

    debut = time.monotonic()
    try:
        reponse = await _appeler_health()
    finally:
        await engine.dispose()
    duree = time.monotonic() - debut

    assert duree < 3
    assert reponse.status_code == 503
    assert reponse.json() == {"statut": "ko", "base": "injoignable"}
