"""Sentence embeddings on CPU through fastembed and ONNX Runtime (ADR-0003 §1).

In production only the API process loads the model; the CLI asks `/internal/embed`.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
from fastembed import TextEmbedding


class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Returns L2-normalised vectors, so inner product and cosine similarity agree."""

    def __init__(self, model_name: str, dimensions: int, cache_dir: Path, *, offline: bool) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._model = TextEmbedding(
            model_name=model_name, cache_dir=str(cache_dir), local_files_only=offline
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = np.stack(list(self._model.embed(list(texts))))
        if vectors.shape[1] != self._dimensions:
            raise ValueError(f"{self._model_name} returned {vectors.shape[1]} dimensions")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        normalised: list[list[float]] = (vectors / norms).tolist()
        return normalised


def download_model(model_name: str, cache_dir: Path) -> None:
    """Fetch the weights into `cache_dir`; image builds and CI call it ahead of time."""
    TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))
