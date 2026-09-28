"""Fixtures transverses : base de données de test et boucle async.

Deux bases sont utilisées (voir `execution.md`) :
- `bl_test` (`TEST_DATABASE_URL`) : toujours à `head`, utilisée par les
  tests qui insèrent des données (invariants de modèles, etc.). Vidée par
  `TRUNCATE ... RESTART IDENTITY CASCADE` après chaque test.
- une base de migrations dédiée aux tests de migration eux-mêmes (aller
  simple `upgrade head`, puis `downgrade base`, puis `upgrade head` à
  nouveau), pour ne jamais perturber `bl_test` pendant qu'un autre test
  suppose qu'elle est à `head`. Son nom est dérivé de celui de la base de
  `TEST_DATABASE_URL` en lui ajoutant le suffixe `_migrations`
  (`bl_test` -> `bl_test_migrations`, `bl_test_wt` -> `bl_test_wt_migrations`,
  L3-D22) : aucune variable d'environnement supplémentaire n'est nécessaire,
  et un second arbre de travail (`TEST_DATABASE_URL` pointant vers une autre
  base) obtient sa propre base de migrations sans se marcher sur les pieds
  de l'arbre principal (constat 9 du plan du lot 3).

Une base injoignable ou une variable absente est un échec explicite
(`pytest.fail`), jamais un `skip` silencieux (décision D13 du brief).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.db import Base, creer_sessionmaker

REPO_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_COMMANDE_DEMARRAGE_POSTGRES = (
    "docker compose --env-file .env -f deploy/docker-compose.yml "
    "-f deploy/docker-compose.dev.yml up -d postgres"
)

load_dotenv(REPO_ROOT / ".env")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def lire_test_database_url() -> str:
    """URL de `bl_test`, ou échec explicite si absente."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "TEST_DATABASE_URL manquante (ni dans l'environnement, ni dans .env). "
            f"Démarrer Postgres de dev : {_COMMANDE_DEMARRAGE_POSTGRES}"
        )
    return url


def url_base_migrations(url_test: str) -> str:
    """URL de la base de migrations, dérivée de celle de `url_test` en
    suffixant son nom de base par `_migrations` (L3-D22) : `bl_test` ->
    `bl_test_migrations`, `bl_test_wt` -> `bl_test_wt_migrations`. Permet à
    un second arbre de travail (`TEST_DATABASE_URL` différente) de tester en
    parallèle sur le même Postgres sans partager sa base de migrations avec
    l'arbre principal (constat 9 du plan du lot 3).

    `str(URL)` masque le mot de passe (`render_as_string(hide_password=True)`
    est le comportement par défaut de `URL.__str__`) : il faut explicitement
    `hide_password=False` pour obtenir une URL réellement utilisable.
    """
    cible = make_url(url_test)
    nom_base = cible.database
    if not nom_base:
        pytest.fail(f"URL de base de test sans nom de base ({_sans_secret(url_test)})")
    url = cible.set(database=f"{nom_base}_migrations")
    return url.render_as_string(hide_password=False)


def _sans_secret(url: str) -> str:
    """Résumé sûr d'une URL de connexion (hôte, port, base), sans identifiants."""
    cible = make_url(url)
    return f"{cible.host}:{cible.port}/{cible.database}"


async def _creer_base_si_absente(url: str) -> None:
    cible = make_url(url)
    nom_base = cible.database
    if not nom_base:
        pytest.fail(f"URL de base de test sans nom de base ({_sans_secret(url)})")
    url_admin = cible.set(database="postgres")
    engine_admin = create_async_engine(url_admin, isolation_level="AUTOCOMMIT")
    try:
        async with engine_admin.connect() as connexion:
            existe = await connexion.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :nom"),
                {"nom": nom_base},
            )
            if not existe:
                await connexion.execute(text(f'CREATE DATABASE "{nom_base}"'))
    finally:
        await engine_admin.dispose()


def preparer_base(url: str) -> None:
    """Crée la base si besoin puis la migre à `head` (appel synchrone)."""
    try:
        asyncio.run(_creer_base_si_absente(url))
    except Exception as exc:
        # Ni l'exception brute (peut embarquer une DSN avec mot de passe
        # selon le pilote) ni l'URL en clair ne sont interpolées : le type
        # d'exception et un résumé sûr (hôte/port/base) suffisent.
        pytest.fail(
            f"Postgres de test injoignable ({type(exc).__name__} sur "
            f"{_sans_secret(url)}). Démarrer : {_COMMANDE_DEMARRAGE_POSTGRES}"
        )
    config = Config(str(ALEMBIC_INI))
    config.attributes["sqlalchemy_url"] = url
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return lire_test_database_url()


@pytest.fixture(scope="session")
def _base_test_prete(test_database_url: str) -> None:
    preparer_base(test_database_url)


@pytest.fixture(scope="session")
def db_engine(test_database_url: str, _base_test_prete: None) -> Iterator[AsyncEngine]:
    # `NullPool` : chaque test tourne dans sa propre boucle asyncio (plugin
    # anyio, backend par fonction) ; un pool par défaut garderait des
    # connexions asyncpg créées dans une boucle déjà fermée, provoquant des
    # `InterfaceError` aléatoires ("another operation is in progress").
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    yield engine

    async def _fermer() -> None:
        await engine.dispose()

    asyncio.run(_fermer())


@pytest.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session de test ; toutes les tables sont vidées après le test."""
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
