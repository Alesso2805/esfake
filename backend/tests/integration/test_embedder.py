"""The real embedding model from config/models.yaml (downloaded once, cached by CI)."""

import math

import pytest

from esfake.pipeline.similarity.embedder import FastEmbedEmbedder
from esfake.shared.config import ModelSettings
from esfake.shared.models_config import load_models_config
from tests.paths import REPO_DIR


@pytest.fixture(scope="module")
def embedder() -> FastEmbedEmbedder:
    settings = ModelSettings()
    embedding = load_models_config(REPO_DIR / "config").embedding
    return FastEmbedEmbedder(embedding, settings.models_dir, offline=False)


def test_vectors_are_normalised_and_384_dimensional(embedder: FastEmbedEmbedder) -> None:
    vectors = embedder.embed(["Hola mamá, cambié de número", "Tu pedido llegó"])

    assert [len(vector) for vector in vectors] == [384, 384]
    assert all(math.isclose(math.hypot(*vector), 1.0, abs_tol=1e-5) for vector in vectors)


def test_paraphrases_are_closer_than_unrelated_messages(embedder: FastEmbedEmbedder) -> None:
    scam, paraphrase, unrelated = embedder.embed(
        [
            "Mamá, cambié de número, deposítame urgente que tuve un accidente",
            "Hola ma, este es mi nuevo número, necesito que me yapees ya, es una emergencia",
            "Tu pedido de supermercado será entregado mañana entre 9 y 11",
        ]
    )

    def cosine(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cosine(scam, paraphrase) > cosine(scam, unrelated)
