"""Verification tables (docs/SPEC.md, Esquema → Verificación)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from esfake.shared.db.base import (
    CHANNELS,
    LEVELS,
    LLM_ROUTES,
    ROUTES,
    Base,
    hmac_format,
    one_of,
    sql_in,
)
from esfake.shared.ids import new_id

# Rule 7 of CLAUDE.md: a queue row fails for good on its fifth attempt.
MAX_DELIVERY_ATTEMPTS = 5


class ChannelIdentity(Base):
    __tablename__ = "channel_identities"
    __table_args__ = (
        UniqueConstraint("channel", "external_id_hmac"),
        one_of("channel", CHANNELS),
        hmac_format("external_id_hmac"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    channel: Mapped[str]
    external_id_hmac: Mapped[str]
    privacy_notice_accepted_at: Mapped[datetime | None]
    pilot_cohort: Mapped[str | None]
    language: Mapped[str | None]
    created_at: Mapped[datetime]


class Verification(Base):
    """One checked message. A trigger refuses identities without an accepted privacy notice."""

    __tablename__ = "verifications"
    __table_args__ = (
        UniqueConstraint("channel", "external_message_hmac"),
        one_of("channel", CHANNELS),
        one_of("status", ("pending", "done", "failed")),
        hmac_format("external_message_hmac"),
        hmac_format("text_hmac"),
        CheckConstraint("channel = 'web' OR identity_id IS NOT NULL", name="identity_required"),
        CheckConstraint(
            "channel = 'web' OR external_message_hmac IS NOT NULL",
            name="external_message_required",
        ),
        CheckConstraint(
            "text_purged_at IS NULL OR text_redacted IS NULL", name="purged_text_empty"
        ),
        CheckConstraint(
            "donated_at IS NULL"
            " OR (consent_version IS NOT NULL AND donation_code_hash IS NOT NULL)",
            name="donation_consent",
        ),
        CheckConstraint("latency_ms >= 0", name="latency_ms_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channel_identities.id"), index=True
    )
    channel: Mapped[str]
    external_message_hmac: Mapped[str | None]
    received_at: Mapped[datetime]
    text_redacted: Mapped[str | None]
    text_hmac: Mapped[str]
    language: Mapped[str | None]
    redaction_counts: Mapped[dict[str, Any]]
    status: Mapped[str]
    manifest_hash: Mapped[str] = mapped_column(ForeignKey("pipeline_manifests.manifest_hash"))
    latency_ms: Mapped[int | None]
    privacy_notice_version: Mapped[str]
    donated_at: Mapped[datetime | None]
    consent_version: Mapped[str | None]
    donation_code_hash: Mapped[str | None]
    text_purged_at: Mapped[datetime | None]


class VerificationQueue(Base):
    """Postgres as the job queue (ADR-0002 §2)."""

    __tablename__ = "verification_queue"
    __table_args__ = (
        CheckConstraint(f"attempts BETWEEN 0 AND {MAX_DELIVERY_ATTEMPTS}", name="attempts_range"),
        CheckConstraint("sent_at IS NULL OR failed_at IS NULL", name="sent_or_failed"),
        Index(
            "ix_verification_queue_ready",
            "available_at",
            postgresql_where=text("failed_at IS NULL AND sent_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    verification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verifications.id"), unique=True)
    # AES-GCM ciphertext with its own key; deleted on send or after 24 h.
    reply_address_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    enqueued_at: Mapped[datetime]
    available_at: Mapped[datetime]
    attempts: Mapped[int]
    last_error: Mapped[str | None]
    sent_at: Mapped[datetime | None]
    failed_at: Mapped[datetime | None]


class Url(Base):
    __tablename__ = "urls"
    __table_args__ = (
        CheckConstraint(
            "(lookalike_of IS NULL) = (lookalike_score IS NULL)", name="lookalike_pair"
        ),
        CheckConstraint("lookalike_score BETWEEN 0 AND 1", name="lookalike_score_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    verification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verifications.id"), index=True)
    url_redacted: Mapped[str | None]
    registered_domain: Mapped[str | None]
    is_shortener: Mapped[bool]
    is_idn: Mapped[bool]
    brand_token: Mapped[str | None]
    lookalike_of: Mapped[str | None]
    lookalike_score: Mapped[float | None]


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        one_of("layer", ("rules", "injection", "urls", "similarity", "llm")),
        CheckConstraint(
            "layer = 'similarity' OR cardinality(neighbor_ids) = 0",
            name="neighbors_from_similarity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    verification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verifications.id"), index=True)
    layer: Mapped[str]
    code: Mapped[str]
    weight: Mapped[float]
    modality_code: Mapped[str | None] = mapped_column(ForeignKey("modalities.code"))
    evidence_spans: Mapped[list[Any]] = mapped_column(JSONB)
    # Corpus ids without a foreign key: a deleted donation shows as "vecino retirado".
    neighbor_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    detail: Mapped[dict[str, Any] | None]


class Verdict(Base):
    __tablename__ = "verdicts"
    __table_args__ = (
        one_of("level", LEVELS),
        one_of("route", ROUTES),
        CheckConstraint(
            "level <> 'likely_scam' OR modality_code IS NOT NULL", name="likely_scam_modality"
        ),
        # llm_used means a call was attempted; a timeout records zero tokens and cost.
        CheckConstraint(
            "(llm_used AND llm_model IS NOT NULL AND prompt_version IS NOT NULL"
            " AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND cost_usd IS NOT NULL)"
            " OR (NOT llm_used AND llm_model IS NULL AND prompt_version IS NULL"
            " AND input_tokens IS NULL AND output_tokens IS NULL AND cost_usd IS NULL)",
            name="llm_fields",
        ),
        CheckConstraint(f"NOT llm_used OR route IN {sql_in(LLM_ROUTES)}", name="llm_route"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cost_usd >= 0", name="usage_non_negative"
        ),
    )

    verification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("verifications.id"), primary_key=True
    )
    level: Mapped[str]
    score: Mapped[float]
    modality_code: Mapped[str | None] = mapped_column(ForeignKey("modalities.code"))
    template_ids: Mapped[list[str]] = mapped_column(ARRAY(Text))
    route: Mapped[str]
    llm_used: Mapped[bool]
    llm_model: Mapped[str | None]
    prompt_version: Mapped[str | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    cost_usd: Mapped[Decimal | None]
    degraded: Mapped[bool]
    decided_at: Mapped[datetime]


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        one_of("user_label", ("scam", "legit", "unsure")),
        CheckConstraint("helpful IS NOT NULL OR user_label IS NOT NULL", name="not_empty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    verification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verifications.id"), unique=True)
    helpful: Mapped[bool | None]
    user_label: Mapped[str | None]
    created_at: Mapped[datetime]
