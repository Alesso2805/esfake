"""Corpus and evaluation tables (docs/SPEC.md, Esquema → Corpus y evaluación)."""

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from esfake.shared.db.base import Base, one_of


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
