"""Real Postgres for integration tests (CLAUDE.md, Definición de hecho).

One pgvector container per session, initialised by the same bootstrap script that Docker
Compose and production use, then migrated to head as esfake_owner.
"""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine
from testcontainers.community.postgres import PostgresContainer

from esfake.corpus.modalities import load_catalog, sync_modalities
from esfake.shared.db import create_engine
from tests.paths import BACKEND_DIR, MODALITIES_YAML

BOOTSTRAP_DIR = BACKEND_DIR / "migrations" / "bootstrap"
POSTGRES_IMAGE = "pgvector/pgvector:0.8.7-pg16"
DATABASE_NAME = "esfake"
# Throwaway credentials for a container that lives only during the test session.
SUPERUSER_PASSWORD = "postgres-test-only"  # noqa: S105
OWNER_PASSWORD = "owner-test-only"  # noqa: S105
APP_PASSWORD = "app-test-only"  # noqa: S105


@dataclass(frozen=True)
class Database:
    host: str
    port: int
    container: PostgresContainer

    def dump(self) -> str:
        """Plain-SQL dump of the whole database, as an attacker with a backup would see it."""
        result = self.container.exec(["pg_dump", "--username", "postgres", DATABASE_NAME])
        assert result.exit_code == 0, result.output
        dump: str = result.output.decode()
        return dump

    def url(self, user: str, password: str) -> str:
        return f"postgresql+asyncpg://{user}:{password}@{self.host}:{self.port}/{DATABASE_NAME}"

    @property
    def superuser_url(self) -> str:
        return self.url("postgres", SUPERUSER_PASSWORD)

    @property
    def owner_url(self) -> str:
        return self.url("esfake_owner", OWNER_PASSWORD)

    @property
    def app_url(self) -> str:
        return self.url("esfake_app", APP_PASSWORD)


def alembic_config(database_url: str) -> Config:
    config = Config(toml_file=BACKEND_DIR / "pyproject.toml")
    config.attributes["database_url"] = database_url
    return config


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    container = (
        PostgresContainer(
            POSTGRES_IMAGE, username="postgres", password=SUPERUSER_PASSWORD, dbname=DATABASE_NAME
        )
        .with_env("ESFAKE_OWNER_PASSWORD", OWNER_PASSWORD)
        .with_env("ESFAKE_APP_PASSWORD", APP_PASSWORD)
        .with_volume_mapping(str(BOOTSTRAP_DIR), "/docker-entrypoint-initdb.d", "ro")
    )
    with container:
        db = Database(
            container.get_container_host_ip(), int(container.get_exposed_port(5432)), container
        )
        command.upgrade(alembic_config(db.owner_url), "head")
        yield db


@pytest.fixture
async def owner_engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.owner_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def seeded_modalities(owner_engine: AsyncEngine) -> None:
    await sync_modalities(owner_engine, load_catalog(MODALITIES_YAML))
