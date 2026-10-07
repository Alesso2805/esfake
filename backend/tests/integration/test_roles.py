"""esfake_app reads and writes data but never changes the schema (ADR-0002 §6)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from esfake.shared.db.models import AuditLog

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE intruder (id int)",
        "ALTER TABLE modalities ADD COLUMN intruder int",
        "DROP TABLE feedback",
        "CREATE INDEX ix_intruder ON verifications (status)",
        "UPDATE alembic_version SET version_num = '0000'",
    ],
)
async def test_app_role_cannot_change_schema_or_migration_history(
    app_engine: AsyncEngine, statement: str
) -> None:
    with pytest.raises(DBAPIError, match=r"permission denied|must be owner"):
        async with app_engine.begin() as conn:
            await conn.execute(text(statement))


async def test_default_privileges_cover_tables_created_later(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE later_table (id int)"))
    try:
        async with app_engine.begin() as conn:
            await conn.execute(text("INSERT INTO later_table VALUES (1)"))
            assert await conn.scalar(text("SELECT count(*) FROM later_table")) == 1
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text("DROP TABLE later_table"))


async def _attempt(conn: AsyncConnection, statement: str, error: str) -> None:
    # A savepoint per attempt keeps the outer transaction usable after each rejection.
    with pytest.raises(DBAPIError, match=error):
        async with conn.begin_nested():
            await conn.execute(text(statement))


@pytest.mark.parametrize(
    ("role", "error"),
    [("app", "permission denied for table audit_log"), ("owner", "audit_log is append-only")],
)
async def test_audit_log_is_append_only(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, role: str, error: str
) -> None:
    engine = app_engine if role == "app" else owner_engine
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            await conn.execute(
                insert(AuditLog).values(
                    actor="cli:alessandro",
                    action="label",
                    entity_type="labeling_task",
                    entity_id="01900000-0000-7000-8000-000000000005",
                    changed_fields=["status", "label"],
                    at=NOW,
                )
            )
            assert await conn.scalar(text("SELECT count(*) FROM audit_log")) >= 1

            await _attempt(conn, "UPDATE audit_log SET actor = 'someone else'", error)
            await _attempt(conn, "DELETE FROM audit_log", error)
            await _attempt(conn, "TRUNCATE audit_log", error)
        finally:
            await transaction.rollback()
