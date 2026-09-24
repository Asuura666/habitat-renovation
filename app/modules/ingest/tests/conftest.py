"""Fixtures locales à `app/modules/ingest/tests/` : `tests/conftest.py` ne
s'applique qu'aux tests situés sous `tests/`, donc ce dossier a besoin de son
propre backend anyio et de sa propre base de test prête (même schéma
`bl_test`, décision D13 : base injoignable = échec explicite, jamais skip).

On réutilise les fonctions pures de `tests/conftest.py` (pas les fixtures,
invisibles ici), comme le fait déjà `app/core/tests/conftest.py`.
"""

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
from app.modules.ingest import commun
from tests.conftest import lire_test_database_url, preparer_base


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _SettingsControlePrix:
    """Substitut minimal de `app.core.config.Settings` : seul
    `controle_prix_actif` est jamais lu, par `ingest.commun
    .controle_prix_actif` (voir `_controle_prix_actif_par_defaut`
    ci-dessous)."""

    def __init__(self, controle_prix_actif: bool) -> None:
        self.controle_prix_actif = controle_prix_actif


@pytest.fixture(autouse=True)
def _controle_prix_actif_par_defaut(monkeypatch: pytest.MonkeyPatch) -> None:
    """Décision d'Ilane du 24/09/2026 (`docs/dette.md`) : le défaut réel de
    l'application (`CONTROLE_PRIX_ACTIF` absente ->
    `Settings.controle_prix_actif = False`) masquerait silencieusement
    toutes les anomalies R07/R08/R09 que les tests d'`ingest` antérieurs à
    cette décision créent en s'attendant à les voir (bilan, tableau de bord,
    comparaison BL, rapprochement…). Cette fixture réenclenche donc le
    drapeau par défaut pour tous les tests de ce paquet ; les tests dédiés au
    masquage (`test_controle_prix.py`) l'écrasent localement avec le même
    idiome pour tester le drapeau désactivé."""
    monkeypatch.setattr(commun, "get_settings", lambda: _SettingsControlePrix(True))


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
    testé (`traiter_fichier`, le routeur) ouvre lui-même ses sessions."""
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
        await connexion.execute(
            text(f"TRUNCATE {noms_tables} RESTART IDENTITY CASCADE")
        )
