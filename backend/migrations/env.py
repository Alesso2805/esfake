"""Alembic environment: migrations run as esfake_owner over asyncpg (ADR-0002 §6).

The URL comes from MIGRATIONS_DATABASE_URL, or from `config.attributes["database_url"]` when a
caller such as the test suite drives Alembic programmatically.
"""

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import esfake.shared.db.models  # noqa: F401  (registers every table on Base.metadata)
from esfake.shared.config import MigrationSettings
from esfake.shared.db.base import Base

target_metadata = Base.metadata


def _database_url() -> str:
    url = context.config.attributes.get("database_url")
    if isinstance(url, str):
        return url
    return MigrationSettings().migrations_database_url.get_secret_value()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) migrations are not supported.")

asyncio.run(_run_online())
