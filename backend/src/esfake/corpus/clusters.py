"""Near-duplicate similarity for the corpus (CLAUDE.md rule 6).

Clustering and the leak test both use this function, with the same threshold from
config/thresholds.yaml: the cosine of the embedding model.
"""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray


def cosine_matrix(vectors: Sequence[Sequence[float]]) -> NDArray[np.float64]:
    matrix = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    unit = matrix / np.where(norms == 0, 1.0, norms)
    similarities: NDArray[np.float64] = unit @ unit.T
    return similarities
