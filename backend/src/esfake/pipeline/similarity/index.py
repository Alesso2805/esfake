"""Exact nearest neighbours over the `index` split, behind one interface (ADR-0002 §5).

Production searches Postgres with `ORDER BY embedding <=> :q LIMIT :k` and no approximate index;
evaluation and CI search the `index` split of the corpus file in memory. Both are exact and
break ties by id, so they return the same neighbours, and an approximate index (HNSW) can come
later behind `SimilarityIndex` with its own ADR.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from esfake.shared.db.models import CorpusMessage

# The corpus labels; the corpus package sits above the pipeline, so they are repeated here.
type NeighborLabel = Literal["scam", "legit"]


@dataclass(frozen=True)
class Neighbor:
    id: str  # corpus_messages.id in Postgres, the case_id in memory
    label: NeighborLabel
    modality: str | None
    similarity: float  # cosine


class SimilarityIndex(Protocol):
    async def nearest(
        self, vector: Sequence[float], k: int, *, label: NeighborLabel | None = None
    ) -> list[Neighbor]:
        """The k most similar `index` messages, optionally of one label, most similar first."""
        ...


@dataclass(frozen=True)
class IndexEntry:
    id: str
    label: NeighborLabel
    modality: str | None


def _unit(vectors: NDArray[np.float64]) -> NDArray[np.float64]:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    unit: NDArray[np.float64] = vectors / np.where(norms == 0, 1.0, norms)
    return unit


class InMemoryIndex:
    """The `index` split held in memory: for evaluation, CI and tests."""

    def __init__(self, entries: Sequence[IndexEntry], vectors: Sequence[Sequence[float]]) -> None:
        if len(entries) != len(vectors):
            raise ValueError("one vector per index entry is required")
        self._entries = tuple(entries)
        matrix = np.asarray(vectors, dtype=np.float64)
        self._vectors = _unit(matrix) if len(entries) else np.zeros((0, 0))

    def __len__(self) -> int:
        return len(self._entries)

    async def nearest(
        self, vector: Sequence[float], k: int, *, label: NeighborLabel | None = None
    ) -> list[Neighbor]:
        if not self._entries:
            return []
        scores = self._vectors @ _unit(np.asarray(vector, dtype=np.float64))
        candidates = [
            (float(score), entry)
            for score, entry in zip(scores, self._entries, strict=True)
            if label is None or entry.label == label
        ]
        candidates.sort(key=lambda item: (-item[0], item[1].id))
        return [
            Neighbor(entry.id, entry.label, entry.modality, score)
            for score, entry in candidates[:k]
        ]


class PgVectorIndex:
    """Exact search over `corpus_messages` rows with `split = 'index'` (production)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def nearest(
        self, vector: Sequence[float], k: int, *, label: NeighborLabel | None = None
    ) -> list[Neighbor]:
        distance = CorpusMessage.embedding.cosine_distance(list(vector))
        query = (
            select(
                CorpusMessage.id,
                CorpusMessage.label,
                CorpusMessage.modality_code,
                (1 - distance).label("similarity"),
            )
            .where(CorpusMessage.split == "index")
            .order_by(distance, CorpusMessage.id)
            .limit(k)
        )
        if label is not None:
            query = query.where(CorpusMessage.label == label)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).all()
        return [
            Neighbor(str(row.id), row.label, row.modality_code, float(row.similarity))
            for row in rows
        ]
