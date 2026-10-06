from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.conftest import Database, alembic_config


async def test_bootstrap_creates_roles_extension_and_ownership(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        roles = await conn.scalars(
            text("SELECT rolname FROM pg_roles WHERE rolname LIKE 'esfake_%' ORDER BY rolname")
        )
        extension = await conn.scalar(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        db_owner = await conn.scalar(
            text(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
            )
        )
        superuser = await conn.scalar(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        )

    assert list(roles) == ["esfake_app", "esfake_owner"]
    assert extension == "vector"
    assert db_owner == "esfake_owner"
    assert superuser is False


def test_migrations_downgrade_to_base_and_upgrade_again(database: Database) -> None:
    config = alembic_config(database.owner_url)

    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_models_match_migrations(database: Database) -> None:
    # Fails when an ORM model and the migrations disagree (`alembic check`).
    command.check(alembic_config(database.owner_url))
