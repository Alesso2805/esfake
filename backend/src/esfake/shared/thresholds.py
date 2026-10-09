"""Decision thresholds from config/thresholds.yaml (CLAUDE.md rule 12)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class RedactionThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name_recall_floor: float = Field(ge=0, le=1)
    name_precision_floor: float = Field(ge=0, le=1)


class CorpusThresholds(BaseModel):
    """EF-07: near-duplicate cut, used by clustering and by the leak test (CLAUDE.md rule 6)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_threshold: float = Field(gt=0, le=1)
    cluster_threshold_reviewed: bool


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    redaction: RedactionThresholds
    corpus: CorpusThresholds


def load_thresholds(config_dir: Path) -> Thresholds:
    path = config_dir / "thresholds.yaml"
    return Thresholds.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
