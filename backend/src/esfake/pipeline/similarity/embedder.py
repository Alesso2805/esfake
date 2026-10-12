"""Sentence embeddings on CPU through fastembed and ONNX Runtime (ADR-0003 §1).

In production only the API process loads the model; the CLI asks `/internal/embed`.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
import onnxruntime
from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from tokenizers import Tokenizer

from esfake.shared.models_config import EmbeddingModelConfig


class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Returns L2-normalised vectors, so inner product and cosine similarity agree."""

    def __init__(self, config: EmbeddingModelConfig, cache_dir: Path, *, offline: bool) -> None:
        self._model_name = config.name
        self._dimensions = config.dimensions
        self._prefix = config.prefix
        # Nothing about this process leaves it unless we send it (ADR-0004).
        onnxruntime.disable_telemetry_events()
        _register(config)
        self._model = TextEmbedding(
            model_name=config.name, cache_dir=str(cache_dir), local_files_only=offline
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = np.stack(list(self._model.embed([self._prefix + text for text in texts])))
        if vectors.shape[1] != self._dimensions:
            raise ValueError(f"{self._model_name} returned {vectors.shape[1]} dimensions")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        normalised: list[list[float]] = (vectors / norms).tolist()
        return normalised

    def _tokenizer(self) -> Tokenizer:
        # fastembed keeps the Hugging Face tokenizer on its backend model.
        tokenizer: Tokenizer = self._model.model.tokenizer  # type: ignore[attr-defined]
        return tokenizer

    @property
    def max_tokens(self) -> int:
        """Where the model truncates its input."""
        truncation = self._tokenizer().truncation
        return int(truncation["max_length"]) if truncation else 0

    def token_counts(self, texts: Sequence[str]) -> list[int]:
        """Tokens per text before truncation, prefix included (ADR-0003, amendment 1)."""
        tokenizer = Tokenizer.from_str(
            self._tokenizer().to_str()
        )  # a copy: the model's keeps truncating
        tokenizer.no_truncation()
        tokenizer.no_padding()
        return [len(e.ids) for e in tokenizer.encode_batch([self._prefix + t for t in texts])]


def _register(config: EmbeddingModelConfig) -> None:
    """fastembed knows only its own catalogue; other ONNX models are registered once per process."""
    if config.onnx is None:
        return
    if any(m["model"] == config.name for m in TextEmbedding.list_supported_models()):
        return
    TextEmbedding.add_custom_model(
        model=config.name,
        pooling=PoolingType.MEAN if config.onnx.pooling == "mean" else PoolingType.CLS,
        normalization=True,
        sources=ModelSource(hf=config.onnx.repository),
        dim=config.dimensions,
        model_file=config.onnx.model_file,
    )


def download_model(config: EmbeddingModelConfig, cache_dir: Path) -> None:
    """Fetch the weights into `cache_dir`; image builds and CI call it ahead of time."""
    _register(config)
    TextEmbedding(model_name=config.name, cache_dir=str(cache_dir))
