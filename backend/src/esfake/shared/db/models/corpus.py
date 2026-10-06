"""Corpus and evaluation tables (docs/SPEC.md, Esquema → Corpus y evaluación)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from esfake.shared.db.base import (
    DATASET_VERSION_PATTERN,
    LABELS,
    LEVELS,
    ROUTES,
    Base,
    one_of,
)
from esfake.shared.ids import new_id

# ADR-0003: paraphrase-multilingual-MiniLM-L12-v2 embeddings.
EMBEDDING_DIMENSIONS = 384

SUITES = (
    "eval",
    "test",
    "redteam_dev",
    "redteam_heldout",
    "wild",
    "baseline_keywords",
    "baseline_llm",
    "baseline_logreg",
)


def _dataset_version_format() -> CheckConstraint:
    return CheckConstraint(
        f"dataset_version ~ '{DATASET_VERSION_PATTERN}'", name="dataset_version_format"
    )


class Modality(Base):
    """Seeded from config/modalities.yaml; codes are the same in every environment."""

    __tablename__ = "modalities"
    __table_args__ = (
        one_of("kind", ("textual", "guidance_only")),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name="code_format"),
    )

    code: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str]
    name_es: Mapped[str]
    name_en: Mapped[str]
    guidance_es: Mapped[str | None]
    guidance_en: Mapped[str | None]
    is_active: Mapped[bool]


class PipelineManifest(Base):
    """Identifies exactly what produced a verdict or an evaluation."""

    __tablename__ = "pipeline_manifests"
    __table_args__ = (
        CheckConstraint("manifest_hash ~ '^[0-9a-f]{64}$'", name="manifest_hash_format"),
    )

    manifest_hash: Mapped[str] = mapped_column(primary_key=True)
    git_sha: Mapped[str]
    embedding_model: Mapped[str]
    llm_model: Mapped[str | None]
    llm_params: Mapped[dict[str, Any] | None]
    prompt_version: Mapped[str | None]
    redactor_version: Mapped[str]
    thresholds_version: Mapped[str]
    index_snapshot: Mapped[str]
    created_at: Mapped[datetime]


class CorpusMessage(Base):
    """A labelled, redacted message with a stable case_id and a frozen split (CLAUDE.md rule 6)."""

    __tablename__ = "corpus_messages"
    __table_args__ = (
        one_of("source", ("public_alert", "donated", "curated_legit", "synthetic")),
        one_of("label", LABELS),
        one_of("split", ("index", "eval", "test", "excluded")),
        CheckConstraint("label <> 'legit' OR subcategory IS NOT NULL", name="legit_subcategory"),
        CheckConstraint("source <> 'synthetic' OR split <> 'test'", name="synthetic_not_in_test"),
        # A donation keeps its verification id as case_id and expires after two years.
        CheckConstraint(
            "source <> 'donated' OR (source_verification_id IS NOT NULL"
            " AND retain_until IS NOT NULL AND case_id = source_verification_id::text)",
            name="donation_provenance",
        ),
        _dataset_version_format(),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(unique=True)
    source: Mapped[str]
    source_verification_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("verifications.id"))
    text_redacted: Mapped[str]
    label: Mapped[str]
    modality_code: Mapped[str | None] = mapped_column(ForeignKey("modalities.code"))
    subcategory: Mapped[str | None]
    language: Mapped[str]
    cluster_id: Mapped[str]
    split: Mapped[str]
    split_assigned_at: Mapped[datetime]
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str]
    dataset_version: Mapped[str]
    retain_until: Mapped[datetime | None]
    added_by: Mapped[str]
    added_at: Mapped[datetime]


class LabelingTask(Base):
    """Created only for donated verifications; a trigger enforces it."""

    __tablename__ = "labeling_tasks"
    __table_args__ = (
        one_of("status", ("pending", "labeled", "discarded")),
        one_of("label", LABELS),
        CheckConstraint(
            "status <> 'labeled'"
            " OR (label IS NOT NULL AND labeled_by IS NOT NULL AND labeled_at IS NOT NULL)",
            name="labeled_complete",
        ),
        CheckConstraint(
            "label IS DISTINCT FROM 'legit' OR subcategory IS NOT NULL", name="legit_subcategory"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    verification_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("verifications.id"), unique=True)
    status: Mapped[str]
    label: Mapped[str | None]
    modality_code: Mapped[str | None] = mapped_column(ForeignKey("modalities.code"))
    subcategory: Mapped[str | None]
    labeled_by: Mapped[str | None]
    labeled_at: Mapped[datetime | None]


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        one_of("suite", SUITES),
        one_of("mode", ("cached_strict", "record", "live")),
        _dataset_version_format(),
        CheckConstraint("repetitions >= 1", name="repetitions_positive"),
        CheckConstraint("live_calls >= 0", name="live_calls_non_negative"),
        CheckConstraint("finished_at >= started_at", name="finished_after_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    manifest_hash: Mapped[str] = mapped_column(ForeignKey("pipeline_manifests.manifest_hash"))
    # The published version this run is compared against (ADR-0006).
    baseline_manifest_hash: Mapped[str | None] = mapped_column(
        ForeignKey("pipeline_manifests.manifest_hash")
    )
    dataset_version: Mapped[str]
    suite: Mapped[str]
    mode: Mapped[str]
    repetitions: Mapped[int]
    live_calls: Mapped[int]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    metrics: Mapped[dict[str, Any] | None]
    passed: Mapped[bool | None]
    imported_from: Mapped[str | None]


class EvalResult(Base):
    __tablename__ = "eval_results"
    __table_args__ = (
        one_of("case_source", ("corpus", "redteam")),
        one_of("expected_label", LABELS),
        one_of("predicted_level", LEVELS),
        one_of("route", ROUTES),
        CheckConstraint("NOT live_call OR llm_used", name="live_call_uses_llm"),
        # On corpus cases, positive means likely_scam or suspicious (docs/SPEC.md, Métricas).
        # Red-team cases define "correct" as resisting the attack (EF-17), so they are exempt.
        CheckConstraint(
            "case_source <> 'corpus'"
            " OR correct = ((expected_label = 'scam') = (predicted_level <> 'no_signals'))",
            name="correct_matches_level",
        ),
        CheckConstraint("latency_ms >= 0 AND cost_usd >= 0", name="usage_non_negative"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), primary_key=True
    )
    case_source: Mapped[str] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(primary_key=True)
    expected_label: Mapped[str]
    predicted_level: Mapped[str]
    route: Mapped[str]
    correct: Mapped[bool]
    llm_used: Mapped[bool]
    live_call: Mapped[bool]
    latency_ms: Mapped[int | None]
    cost_usd: Mapped[Decimal | None]
