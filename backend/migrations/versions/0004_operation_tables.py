"""Operation tables, with audit_log append-only.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06 15:44:32.991579
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# audit_log is append-only for every role, the owner included (EF-03). Revoking privileges
# stops esfake_app; the triggers also stop the owner, short of dropping them on purpose.
REJECT_AUDIT_CHANGE = """
CREATE FUNCTION esfake_reject_audit_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % rejected', TG_OP;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("changed_fields", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_table(
        "rate_limit_windows",
        sa.Column("key_hmac", sa.Text(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("window_kind", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "key_hmac ~ '^[A-Za-z0-9_-]{1,32}:[0-9a-f]{64}$'",
            name=op.f("ck_rate_limit_windows_key_hmac_format"),
        ),
        sa.CheckConstraint(
            "window_kind IN ('minute', 'day')", name=op.f("ck_rate_limit_windows_window_kind_valid")
        ),
        sa.CheckConstraint(
            "request_count >= 0", name=op.f("ck_rate_limit_windows_request_count_non_negative")
        ),
        sa.PrimaryKeyConstraint(
            "key_hmac", "route", "window_kind", "window_start", name=op.f("pk_rate_limit_windows")
        ),
    )
    op.create_table(
        "spend_ledger",
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("period_kind", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("free_quota", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("billable_units", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("cap_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("capped_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "period_kind IN ('month', 'day')", name=op.f("ck_spend_ledger_period_kind_valid")
        ),
        sa.CheckConstraint(
            "scope = 'llm' OR period_kind = 'month'",
            name=op.f("ck_spend_ledger_daily_only_for_llm"),
        ),
        sa.CheckConstraint(
            "scope IN ('whatsapp', 'llm')", name=op.f("ck_spend_ledger_scope_valid")
        ),
        sa.CheckConstraint(
            "billable_units <= units", name=op.f("ck_spend_ledger_billable_within_units")
        ),
        sa.CheckConstraint(
            "cost_usd >= 0 AND cap_usd >= 0", name=op.f("ck_spend_ledger_money_non_negative")
        ),
        sa.CheckConstraint(
            "free_quota >= 0 AND units >= 0 AND billable_units >= 0",
            name=op.f("ck_spend_ledger_units_non_negative"),
        ),
        sa.PrimaryKeyConstraint(
            "scope", "period_kind", "period_start", name=op.f("pk_spend_ledger")
        ),
    )
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM esfake_app")
    op.execute(REJECT_AUDIT_CHANGE)
    op.execute(
        "CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log"
        " FOR EACH ROW EXECUTE FUNCTION esfake_reject_audit_change()"
    )
    op.execute(
        "CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log"
        " FOR EACH STATEMENT EXECUTE FUNCTION esfake_reject_audit_change()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_log_no_truncate ON audit_log")
    op.execute("DROP TRIGGER audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION esfake_reject_audit_change()")
    op.drop_table("spend_ledger")
    op.drop_table("rate_limit_windows")
    op.drop_table("audit_log")
