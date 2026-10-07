"""Corpus and evaluation tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06 15:42:11.966645
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Labeling tasks exist only for donated verifications (docs/SPEC.md, Esquema).
REQUIRE_DONATION = """
CREATE FUNCTION esfake_require_donation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM verifications WHERE id = NEW.verification_id AND donated_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'verification % was not donated', NEW.verification_id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("manifest_hash", sa.Text(), nullable=False),
        sa.Column("baseline_manifest_hash", sa.Text(), nullable=True),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("suite", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("live_calls", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("imported_from", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "dataset_version ~ '^[0-9]+\\.[0-9]+$'",
            name=op.f("ck_eval_runs_dataset_version_format"),
        ),
        sa.CheckConstraint(
            "mode IN ('cached_strict', 'record', 'live')", name=op.f("ck_eval_runs_mode_valid")
        ),
        sa.CheckConstraint(
            "suite IN ('eval', 'test', 'redteam_dev', 'redteam_heldout', 'wild', 'baseline_keywords', 'baseline_llm', 'baseline_logreg')",
            name=op.f("ck_eval_runs_suite_valid"),
        ),
        sa.CheckConstraint(
            "finished_at >= started_at", name=op.f("ck_eval_runs_finished_after_start")
        ),
        sa.CheckConstraint("live_calls >= 0", name=op.f("ck_eval_runs_live_calls_non_negative")),
        sa.CheckConstraint("repetitions >= 1", name=op.f("ck_eval_runs_repetitions_positive")),
        sa.ForeignKeyConstraint(
            ["baseline_manifest_hash"],
            ["pipeline_manifests.manifest_hash"],
            name=op.f("fk_eval_runs_baseline_manifest_hash_pipeline_manifests"),
        ),
        sa.ForeignKeyConstraint(
            ["manifest_hash"],
            ["pipeline_manifests.manifest_hash"],
            name=op.f("fk_eval_runs_manifest_hash_pipeline_manifests"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
    )
    op.create_table(
        "corpus_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_verification_id", sa.Uuid(), nullable=True),
        sa.Column("text_redacted", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("modality_code", sa.Text(), nullable=True),
        sa.Column("subcategory", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("cluster_id", sa.Text(), nullable=False),
        sa.Column("split", sa.Text(), nullable=False),
        sa.Column("split_assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("dataset_version", sa.Text(), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("added_by", sa.Text(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "dataset_version ~ '^[0-9]+\\.[0-9]+$'",
            name=op.f("ck_corpus_messages_dataset_version_format"),
        ),
        sa.CheckConstraint(
            "label <> 'legit' OR subcategory IS NOT NULL",
            name=op.f("ck_corpus_messages_legit_subcategory"),
        ),
        sa.CheckConstraint(
            "label IN ('scam', 'legit')", name=op.f("ck_corpus_messages_label_valid")
        ),
        sa.CheckConstraint(
            "source <> 'donated' OR (source_verification_id IS NOT NULL AND retain_until IS NOT NULL AND case_id = source_verification_id::text)",
            name=op.f("ck_corpus_messages_donation_provenance"),
        ),
        sa.CheckConstraint(
            "source <> 'synthetic' OR split <> 'test'",
            name=op.f("ck_corpus_messages_synthetic_not_in_test"),
        ),
        sa.CheckConstraint(
            "source IN ('public_alert', 'donated', 'curated_legit', 'synthetic')",
            name=op.f("ck_corpus_messages_source_valid"),
        ),
        sa.CheckConstraint(
            "split IN ('index', 'eval', 'test', 'excluded')",
            name=op.f("ck_corpus_messages_split_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["modality_code"],
            ["modalities.code"],
            name=op.f("fk_corpus_messages_modality_code_modalities"),
        ),
        sa.ForeignKeyConstraint(
            ["source_verification_id"],
            ["verifications.id"],
            name=op.f("fk_corpus_messages_source_verification_id_verifications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corpus_messages")),
        sa.UniqueConstraint("case_id", name=op.f("uq_corpus_messages_case_id")),
    )
    op.create_table(
        "eval_results",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("case_source", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("expected_label", sa.Text(), nullable=False),
        sa.Column("predicted_level", sa.Text(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("llm_used", sa.Boolean(), nullable=False),
        sa.Column("live_call", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.CheckConstraint(
            "case_source <> 'corpus' OR correct = ((expected_label = 'scam') = (predicted_level <> 'no_signals'))",
            name=op.f("ck_eval_results_correct_matches_level"),
        ),
        sa.CheckConstraint(
            "case_source IN ('corpus', 'redteam')", name=op.f("ck_eval_results_case_source_valid")
        ),
        sa.CheckConstraint(
            "expected_label IN ('scam', 'legit')", name=op.f("ck_eval_results_expected_label_valid")
        ),
        sa.CheckConstraint(
            "predicted_level IN ('likely_scam', 'suspicious', 'no_signals')",
            name=op.f("ck_eval_results_predicted_level_valid"),
        ),
        sa.CheckConstraint(
            "route IN ('early_exit', 'gray_zone', 'risk_trait', 'out_of_distribution', 'no_route')",
            name=op.f("ck_eval_results_route_valid"),
        ),
        sa.CheckConstraint(
            "NOT live_call OR llm_used", name=op.f("ck_eval_results_live_call_uses_llm")
        ),
        sa.CheckConstraint(
            "latency_ms >= 0 AND cost_usd >= 0", name=op.f("ck_eval_results_usage_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["eval_runs.id"],
            name=op.f("fk_eval_results_run_id_eval_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", "case_source", "case_id", name=op.f("pk_eval_results")),
    )
    op.create_table(
        "labeling_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("verification_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("modality_code", sa.Text(), nullable=True),
        sa.Column("subcategory", sa.Text(), nullable=True),
        sa.Column("labeled_by", sa.Text(), nullable=True),
        sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "label IN ('scam', 'legit')", name=op.f("ck_labeling_tasks_label_valid")
        ),
        sa.CheckConstraint(
            "label IS DISTINCT FROM 'legit' OR subcategory IS NOT NULL",
            name=op.f("ck_labeling_tasks_legit_subcategory"),
        ),
        sa.CheckConstraint(
            "status <> 'labeled' OR (label IS NOT NULL AND labeled_by IS NOT NULL AND labeled_at IS NOT NULL)",
            name=op.f("ck_labeling_tasks_labeled_complete"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'labeled', 'discarded')",
            name=op.f("ck_labeling_tasks_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["modality_code"],
            ["modalities.code"],
            name=op.f("fk_labeling_tasks_modality_code_modalities"),
        ),
        sa.ForeignKeyConstraint(
            ["verification_id"],
            ["verifications.id"],
            name=op.f("fk_labeling_tasks_verification_id_verifications"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labeling_tasks")),
        sa.UniqueConstraint("verification_id", name=op.f("uq_labeling_tasks_verification_id")),
    )
    op.execute(REQUIRE_DONATION)
    op.execute(
        "CREATE TRIGGER labeling_tasks_require_donation"
        " BEFORE INSERT OR UPDATE OF verification_id ON labeling_tasks"
        " FOR EACH ROW EXECUTE FUNCTION esfake_require_donation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER labeling_tasks_require_donation ON labeling_tasks")
    op.execute("DROP FUNCTION esfake_require_donation()")
    op.drop_table("labeling_tasks")
    op.drop_table("eval_results")
    op.drop_table("corpus_messages")
    op.drop_table("eval_runs")
