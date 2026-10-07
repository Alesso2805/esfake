"""Foundations: pgvector and default privileges for esfake_app.

Revision ID: 0001
Revises:
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The bootstrap script already created it as superuser, so this is a no-op there; it still
    # works where a provider lets the database owner create the extension (ADR-0002 §6).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Every table and sequence esfake_owner creates from now on is usable by the runtime role,
    # which never gets DDL rights. Tables that need less (audit_log) revoke it explicitly.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE esfake_owner IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO esfake_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE esfake_owner IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO esfake_app"
    )


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE esfake_owner IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM esfake_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE esfake_owner IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM esfake_app"
    )
    # The extension belongs to the bootstrap script, not to this migration.
