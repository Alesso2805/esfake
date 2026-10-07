from collections.abc import Sequence


class FakeEmbedder:
    model_name = "fake-embedder"
    dimensions = 384

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * (self.dimensions - 1) for _ in texts]
