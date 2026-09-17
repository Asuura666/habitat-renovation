"""`messaging` ne touche ni base ni réseau réel (tests via
`httpx.MockTransport`) : seul le backend anyio est nécessaire ici."""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
