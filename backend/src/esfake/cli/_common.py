"""Defaults and helpers shared by the CLI modules (paths are relative to `backend/`)."""

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from esfake.shared.config import ModelSettings
from esfake.shared.models_config import load_models_config

if TYPE_CHECKING:
    from esfake.pipeline.similarity.embedder import FastEmbedEmbedder

DEFAULT_CORPUS = Path("../evals/datasets/corpus.jsonl")


def local_embedder(contender: bool = False) -> FastEmbedEmbedder:
    """In development and CI the CLI loads the model itself; production uses /internal/embed.

    `contender` loads the model the EF-07 checkpoint compares against (ADR-0003, amendment 1).
    """
    from esfake.pipeline.similarity.embedder import FastEmbedEmbedder

    settings = ModelSettings()
    models = load_models_config(settings.config_dir)
    config = models.embedding_contender if contender else models.embedding
    if config is None:
        raise typer.BadParameter("config/models.yaml names no embedding_contender")
    return FastEmbedEmbedder(config, settings.models_dir, offline=settings.models_offline)
