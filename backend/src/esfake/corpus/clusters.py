"""Near-duplicate similarity for the corpus (CLAUDE.md rule 6).

Clustering and the leak test both use this function, with the same threshold from
config/thresholds.yaml: the cosine of the embedding model.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from esfake.corpus.dataset import CorpusRecord


def cosine_matrix(vectors: Sequence[Sequence[float]]) -> NDArray[np.float64]:
    matrix = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    unit = matrix / np.where(norms == 0, 1.0, norms)
    similarities: NDArray[np.float64] = unit @ unit.T
    return similarities


@dataclass(frozen=True)
class Leak:
    held_out: str
    index: str
    similarity: float


def find_leaks(
    records: Sequence[CorpusRecord], vectors: Sequence[Sequence[float]], threshold: float
) -> list[Leak]:
    """Every eval or test message with an `index` neighbour at or above the cluster threshold."""
    similarities = cosine_matrix(vectors)
    index = [i for i, r in enumerate(records) if r.split == "index"]
    held_out = [i for i, r in enumerate(records) if r.split in ("eval", "test")]
    return [
        Leak(str(records[h].case_id), str(records[i].case_id), float(similarities[h, i]))
        for h in held_out
        for i in index
        if similarities[h, i] >= threshold
    ]
