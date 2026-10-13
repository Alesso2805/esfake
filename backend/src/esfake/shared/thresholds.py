"""Decision thresholds from config/thresholds.yaml (CLAUDE.md rule 12)."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class RedactionThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name_recall_floor: float = Field(ge=0, le=1)
    name_precision_floor: float = Field(ge=0, le=1)


class CorpusThresholds(BaseModel):
    """EF-07: near-duplicate cut, used by clustering and by the leak test (CLAUDE.md rule 6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_threshold: float = Field(gt=0, le=1)
    cluster_threshold_reviewed: bool


class PolicyV0Thresholds(BaseModel):
    """EF-08: levels from the sum of signal weights, until EF-15."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suspicious_at: float = Field(gt=0)
    likely_scam_at: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.likely_scam_at <= self.suspicious_at:
            raise ValueError("likely_scam_at must be above suspicious_at")
        return self


class SimilarityThresholds(BaseModel):
    """EF-13: when similarity to known scams decides (ADR-0002 §5, ADR-0003 §6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    k: int = Field(ge=1)
    delta: float = Field(ge=0, le=1)
    calibrated: bool
    weight: float = Field(gt=0)  # positive: similarity never lowers a verdict


class UrlThresholds(BaseModel):
    """EF-12: how close to an official domain counts as imitating it (ADR-0005 §2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lookalike_min_similarity: float = Field(gt=0, le=1)


class EvaluationThresholds(BaseModel):
    """ADR-0006 B: absolute floors on `eval`, enforced only when enabled."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    absolute_floors_enabled: bool
    recall_floor: float = Field(ge=0, le=1)
    false_positive_ceiling: float = Field(ge=0, le=1)


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    redaction: RedactionThresholds
    corpus: CorpusThresholds
    policy_v0: PolicyV0Thresholds
    similarity: SimilarityThresholds
    urls: UrlThresholds
    evaluation: EvaluationThresholds


def load_thresholds(config_dir: Path) -> Thresholds:
    path = config_dir / "thresholds.yaml"
    return Thresholds.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
