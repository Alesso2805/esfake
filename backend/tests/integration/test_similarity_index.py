"""Exact search in Postgres agrees with the in-memory index (ADR-0002 §5, EF-13).

The rows are committed so that `PgVectorIndex` sees them through its own connection, and removed
at the end.
"""

import random
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncEngine

from esfake.pipeline.similarity.index import (
    IndexEntry,
    InMemoryIndex,
    NeighborLabel,
    PgVectorIndex,
)
from esfake.shared.db.models import CorpusMessage

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
DIMENSIONS = 384


def _vector(rng: random.Random) -> list[float]:
    return [rng.gauss(0, 1) for _ in range(DIMENSIONS)]


@pytest.fixture
async def stored(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, seeded_modalities: None
) -> AsyncIterator[tuple[InMemoryIndex, list[list[float]]]]:
    rng = random.Random(13)  # noqa: S311 (test data, not cryptographic)
    rows, entries, vectors = [], [], []
    for n in range(24):
        row_id = uuid.UUID(int=0x0199_0000_0000_7000_8000_0000_0000_0000 + n)
        label: NeighborLabel = "scam" if n % 3 else "legit"
        modality = "fake_prize" if label == "scam" else None
        split = "eval" if n >= 20 else "index"  # eval rows must never be found
        vector = _vector(rng)
        rows.append(
            {
                "id": row_id,
                "case_id": f"sim-test-{n}",
                "source": "public_alert" if label == "scam" else "curated_legit",
                "text_redacted": f"mensaje {n}",
                "label": label,
                "modality_code": modality,
                "subcategory": None if label == "scam" else "easy",
                "language": "es",
                "cluster_id": f"cl_sim_{n}",
                "split": split,
                "split_assigned_at": NOW,
                "embedding": vector,
                "embedding_model": "test",
                "dataset_version": "1.0",
                "added_by": "similarity-test",
                "added_at": NOW,
            }
        )
        if split == "index":
            entries.append(IndexEntry(str(row_id), label, modality))
            vectors.append(vector)
    async with app_engine.begin() as conn:
        await conn.execute(insert(CorpusMessage), rows)
    try:
        yield InMemoryIndex(entries, vectors), [_vector(rng) for _ in range(5)]
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                delete(CorpusMessage).where(CorpusMessage.added_by == "similarity-test")
            )


@pytest.mark.parametrize("label", [None, "scam", "legit"])
async def test_postgres_and_memory_return_the_same_neighbours(
    app_engine: AsyncEngine,
    stored: tuple[InMemoryIndex, list[list[float]]],
    label: NeighborLabel | None,
) -> None:
    memory, queries = stored
    database = PgVectorIndex(app_engine)

    for query in queries:
        expected = await memory.nearest(query, 5, label=label)
        found = await database.nearest(query, 5, label=label)

        assert [n.id for n in found] == [n.id for n in expected]
        assert [n.label for n in found] == [n.label for n in expected]
        for got, want in zip(found, expected, strict=True):
            assert got.similarity == pytest.approx(want.similarity, abs=1e-5)


async def test_only_the_index_split_is_searched(
    app_engine: AsyncEngine, stored: tuple[InMemoryIndex, list[list[float]]]
) -> None:
    memory, _ = stored

    found = await PgVectorIndex(app_engine).nearest([1.0] * DIMENSIONS, 100)

    assert len(found) == len(memory) == 20
