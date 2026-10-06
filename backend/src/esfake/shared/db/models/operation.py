"""Operation tables (docs/SPEC.md, Esquema → Operación)."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Identity, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from esfake.shared.db.base import Base, hmac_format, one_of


class SpendLedger(Base):
    """WhatsApp and model spend per month, plus the model's daily sub-cap (ADR-0003 §3)."""

    __tablename__ = "spend_ledger"
    __table_args__ = (
        one_of("scope", ("whatsapp", "llm")),
        one_of("period_kind", ("month", "day")),
        CheckConstraint("scope = 'llm' OR period_kind = 'month'", name="daily_only_for_llm"),
        CheckConstraint(
            "free_quota >= 0 AND units >= 0 AND billable_units >= 0", name="units_non_negative"
        ),
        CheckConstraint("billable_units <= units", name="billable_within_units"),
        CheckConstraint("cost_usd >= 0 AND cap_usd >= 0", name="money_non_negative"),
    )

    scope: Mapped[str] = mapped_column(primary_key=True)
    period_kind: Mapped[str] = mapped_column(primary_key=True)
    period_start: Mapped[date] = mapped_column(primary_key=True)
    free_quota: Mapped[int]
    units: Mapped[int]
    billable_units: Mapped[int]
    cost_usd: Mapped[Decimal]
    cap_usd: Mapped[Decimal]
    capped_at: Mapped[datetime | None]


class RateLimitWindow(Base):
    __tablename__ = "rate_limit_windows"
    __table_args__ = (
        one_of("window_kind", ("minute", "day")),
        hmac_format("key_hmac"),
        CheckConstraint("request_count >= 0", name="request_count_non_negative"),
    )

    key_hmac: Mapped[str] = mapped_column(primary_key=True)
    route: Mapped[str] = mapped_column(primary_key=True)
    window_kind: Mapped[str] = mapped_column(primary_key=True)
    window_start: Mapped[datetime] = mapped_column(primary_key=True)
    request_count: Mapped[int]


class AuditLog(Base):
    """Append-only and never holds message text.

    esfake_app may only insert and read; a trigger rejects UPDATE, DELETE and TRUNCATE for every
    role, the owner included.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    actor: Mapped[str]
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[str]
    changed_fields: Mapped[list[str]] = mapped_column(ARRAY(Text))
    at: Mapped[datetime]
