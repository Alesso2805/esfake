"""The versioned list of models (config/models.yaml, ADR-0003)."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from esfake.shared.db.models.corpus import EMBEDDING_DIMENSIONS


class EmbeddingModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    runtime: Literal["fastembed"]
    dimensions: Literal[384]


class SpacyModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str | None


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    embedding: EmbeddingModelConfig
    spacy: SpacyModelConfig


def load_models_config(config_dir: Path) -> ModelsConfig:
    config = ModelsConfig.model_validate(
        yaml.safe_load((config_dir / "models.yaml").read_text(encoding="utf-8"))
    )
    if config.embedding.dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError("embedding dimensions must match corpus_messages.embedding")
    return config
