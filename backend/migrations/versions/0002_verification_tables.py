"""Verification tables, plus the modalities and manifests they reference.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 15:38:07.198802
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# CLAUDE.md rule 5: no verification is created for an identity that has not accepted the
# privacy notice. The application checks it too; the trigger holds even if the code forgets.
REQUIRE_PRIVACY_NOTICE = """
CREATE FUNCTION esfake_require_privacy_notice() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.identity_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM channel_identities
        WHERE id = NEW.identity_id AND privacy_notice_accepted_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'identity % has not accepted the privacy notice', NEW.identity_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "channel_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("external_id_hmac", sa.Text(), nullable=False),
        sa.Column("privacy_notice_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pilot_cohort", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "channel IN ('web', 'whatsapp', 'telegram')",
            name=op.f("ck_channel_identities_channel_valid"),
        ),
        sa.CheckConstraint(
            "external_id_hmac ~ '^[A-Za-z0-9_-]{1,32}:[0-9a-f]{64}$'",
            name=op.f("ck_channel_identities_external_id_hmac_format"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_channel_identities")),
        sa.UniqueConstraint(
            "channel",
            "external_id_hmac",
            name=op.f("uq_channel_identities_channel_external_id_hmac"),
        ),
    )
    op.create_table(
        "modalities",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name_es", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("guidance_es", sa.Text(), nullable=True),
        sa.Column("guidance_en", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name=op.f("ck_modalities_code_format")),
        sa.CheckConstraint(
            "kind IN ('textual', 'guidance_only')", name=op.f("ck_modalities_kind_valid")
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_modalities")),
    )
    op.create_table(
        "pipeline_manifests",
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("git_sha", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("llm_model", sa.Text(), nullable=True),
        sa.Column("llm_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("redactor_version", sa.Text(), nullable=False),
        sa.Column("thresholds_version", sa.Text(), nullable=False),
        sa.Column("index_snapshot", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "manifest_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_pipeline_manifests_manifest_hash_format"),
        ),
        sa.PrimaryKeyConstraint("manifest_hash", name=op.f("pk_pipeline_manifests")),
    )
    op.create_table(
        "verifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("external_message_hmac", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text_redacted", sa.Text(), nullable=True),
        sa.Column("text_hmac", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("redaction_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("privacy_notice_version", sa.Text(), nullable=False),
        sa.Column("donated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_version", sa.Text(), nullable=True),
        sa.Column("donation_code_hash", sa.Text(), nullable=True),
        sa.Column("text_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "channel = 'web' OR external_message_hmac IS NOT NULL",
            name=op.f("ck_verifications_external_message_required"),
        ),
        sa.CheckConstraint(
            "channel = 'web' OR identity_id IS NOT NULL",
            name=op.f("ck_verifications_identity_required"),
        ),
        sa.CheckConstraint(
            "channel IN ('web', 'whatsapp', 'telegram')",
            name=op.f("ck_verifications_channel_valid"),
        ),
        sa.CheckConstraint(
            "external_message_hmac ~ '^[A-Za-z0-9_-]{1,32}:[0-9a-f]{64}$'",
            name=op.f("ck_verifications_external_message_hmac_format"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'done', 'failed')", name=op.f("ck_verifications_status_valid")
        ),
        sa.CheckConstraint(
            "text_hmac ~ '^[A-Za-z0-9_-]{1,32}:[0-9a-f]{64}$'",
            name=op.f("ck_verifications_text_hmac_format"),
        ),
        sa.CheckConstraint(
            "donated_at IS NULL OR (consent_version IS NOT NULL AND donation_code_hash IS NOT NULL)",
            name=op.f("ck_verifications_donation_consent"),
        ),
        sa.CheckConstraint(
            "latency_ms >= 0", name=op.f("ck_verifications_latency_ms_non_negative")
        ),
        sa.CheckConstraint(
            "text_purged_at IS NULL OR text_redacted IS NULL",
            name=op.f("ck_verifications_purged_text_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["channel_identities.id"],
            name=op.f("fk_verifications_identity_id_channel_identities"),
        ),
        sa.ForeignKeyConstraint(
            ["manifest_hash"],
            ["pipeline_manifests.manifest_hash"],
            name=op.f("fk_verifications_manifest_hash_pipeline_manifests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verifications")),
        sa.UniqueConstraint(
            "channel",
            "external_message_hmac",
            name=op.f("uq_verifications_channel_external_message_hmac"),
        ),
    )
    op.create_index(
        op.f("ix_verifications_identity_id"), "verifications", ["identity_id"], unique=False
    )
    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("verification_id", sa.Uuid(), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=True),
        sa.Column("user_label", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "user_label IN ('scam', 'legit', 'unsure')", name=op.f("ck_feedback_user_label_valid")
        ),
        sa.CheckConstraint(
            "helpful IS NOT NULL OR user_label IS NOT NULL", name=op.f("ck_feedback_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["verification_id"],
            ["verifications.id"],
            name=op.f("fk_feedback_verification_id_verifications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
        sa.UniqueConstraint("verification_id", name=op.f("uq_feedback_verification_id")),
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("verification_id", sa.Uuid(), nullable=False),
        sa.Column("layer", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("weight", sa.Double(), nullable=False),
        sa.Column("modality_code", sa.Text(), nullable=True),
        sa.Column("evidence_spans", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("neighbor_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "layer = 'similarity' OR cardinality(neighbor_ids) = 0",
            name=op.f("ck_signals_neighbors_from_similarity"),
        ),
        sa.CheckConstraint(
            "layer IN ('rules', 'injection', 'urls', 'similarity', 'llm')",
            name=op.f("ck_signals_layer_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["modality_code"], ["modalities.code"], name=op.f("fk_signals_modality_code_modalities")
        ),
        sa.ForeignKeyConstraint(
            ["verification_id"],
            ["verifications.id"],
            name=op.f("fk_signals_verification_id_verifications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
    )
    op.create_index(
        op.f("ix_signals_verification_id"), "signals", ["verification_id"], unique=False
    )
    op.create_table(
        "urls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("verification_id", sa.Uuid(), nullable=False),
        sa.Column("url_redacted", sa.Text(), nullable=True),
        sa.Column("registered_domain", sa.Text(), nullable=True),
        sa.Column("is_shortener", sa.Boolean(), nullable=False),
        sa.Column("is_idn", sa.Boolean(), nullable=False),
        sa.Column("brand_token", sa.Text(), nullable=True),
        sa.Column("lookalike_of", sa.Text(), nullable=True),
        sa.Column("lookalike_score", sa.Double(), nullable=True),
        sa.CheckConstraint(
            "(lookalike_of IS NULL) = (lookalike_score IS NULL)",
            name=op.f("ck_urls_lookalike_pair"),
        ),
        sa.CheckConstraint(
            "lookalike_score BETWEEN 0 AND 1", name=op.f("ck_urls_lookalike_score_range")
        ),
        sa.ForeignKeyConstraint(
            ["verification_id"],
            ["verifications.id"],
            name=op.f("fk_urls_verification_id_verifications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_urls")),
    )
    op.create_index(op.f("ix_urls_verification_id"), "urls", ["verification_id"], unique=False)
    op.create_table(
        "verdicts",
        sa.Column("verification_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("modality_code", sa.Text(), nullable=True),
        sa.Column("template_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("llm_used", sa.Boolean(), nullable=False),
        sa.Column("llm_model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("degraded", sa.Boolean(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "NOT llm_used OR route IN ('gray_zone', 'risk_trait', 'out_of_distribution')",
            name=op.f("ck_verdicts_llm_route"),
        ),
        sa.CheckConstraint(
            "level <> 'likely_scam' OR modality_code IS NOT NULL",
            name=op.f("ck_verdicts_likely_scam_modality"),
        ),
        sa.CheckConstraint(
            "level IN ('likely_scam', 'suspicious', 'no_signals')",
            name=op.f("ck_verdicts_level_valid"),
        ),
        sa.CheckConstraint(
            "route IN ('early_exit', 'gray_zone', 'risk_trait', 'out_of_distribution', 'no_route')",
            name=op.f("ck_verdicts_route_valid"),
        ),
        sa.CheckConstraint(
            "(llm_used AND llm_model IS NOT NULL AND prompt_version IS NOT NULL AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND cost_usd IS NOT NULL) OR (NOT llm_used AND llm_model IS NULL AND prompt_version IS NULL AND input_tokens IS NULL AND output_tokens IS NULL AND cost_usd IS NULL)",
            name=op.f("ck_verdicts_llm_fields"),
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cost_usd >= 0",
            name=op.f("ck_verdicts_usage_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["modality_code"],
            ["modalities.code"],
            name=op.f("fk_verdicts_modality_code_modalities"),
        ),
        sa.ForeignKeyConstraint(
            ["verification_id"],
            ["verifications.id"],
            name=op.f("fk_verdicts_verification_id_verifications"),
        ),
        sa.PrimaryKeyConstraint("verification_id", name=op.f("pk_verdicts")),
    )
    op.create_table(
        "verification_queue",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("verification_id", sa.Uuid(), nullable=False),
        sa.Column("reply_address_enc", sa.LargeBinary(), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 5", name=op.f("ck_verification_queue_attempts_range")
        ),
        sa.CheckConstraint(
            "sent_at IS NULL OR failed_at IS NULL",
            name=op.f("ck_verification_queue_sent_or_failed"),
        ),
        sa.ForeignKeyConstraint(
            ["verification_id"],
            ["verifications.id"],
            name=op.f("fk_verification_queue_verification_id_verifications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verification_queue")),
        sa.UniqueConstraint("verification_id", name=op.f("uq_verification_queue_verification_id")),
    )
    op.create_index(
        "ix_verification_queue_ready",
        "verification_queue",
        ["available_at"],
        unique=False,
        postgresql_where=sa.text("failed_at IS NULL AND sent_at IS NULL"),
    )
    op.execute(REQUIRE_PRIVACY_NOTICE)
    op.execute(
        "CREATE TRIGGER verifications_require_privacy_notice"
        " BEFORE INSERT OR UPDATE OF identity_id ON verifications"
        " FOR EACH ROW EXECUTE FUNCTION esfake_require_privacy_notice()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER verifications_require_privacy_notice ON verifications")
    op.execute("DROP FUNCTION esfake_require_privacy_notice()")
    op.drop_index(
        "ix_verification_queue_ready",
        table_name="verification_queue",
        postgresql_where=sa.text("failed_at IS NULL AND sent_at IS NULL"),
    )
    op.drop_table("verification_queue")
    op.drop_table("verdicts")
    op.drop_index(op.f("ix_urls_verification_id"), table_name="urls")
    op.drop_table("urls")
    op.drop_index(op.f("ix_signals_verification_id"), table_name="signals")
    op.drop_table("signals")
    op.drop_table("feedback")
    op.drop_index(op.f("ix_verifications_identity_id"), table_name="verifications")
    op.drop_table("verifications")
    op.drop_table("pipeline_manifests")
    op.drop_table("modalities")
    op.drop_table("channel_identities")
