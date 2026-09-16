"""Environnement Alembic, en mode async.

L'URL de connexion vient de `app.core.config.get_settings()` (donc du
`.env`), jamais de `alembic.ini`. Les tests peuvent la surcharger via
`config.attributes["sqlalchemy_url"]`, pour migrer `bl_test` /
`bl_test_migrations` sans jamais toucher la base de dev.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings
from app.core.db import Base

# Importé pour son effet de bord : enregistre les 14 tables sur
# `Base.metadata`, nécessaire à l'autogénération et à `alembic check`.
from app.modules.ingest import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    surcharge = config.attributes.get("sqlalchemy_url")
    if surcharge:
        return str(surcharge)
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Génère le SQL sans se connecter à une base (mode `--sql`)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    connectable: AsyncEngine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
