"""The in-memory similarity index (ADR-0002 §5): exact, ordered, filtered by label."""

import math

import pytest

from esfake.pipeline.similarity.index import IndexEntry, InMemoryIndex


def at(degrees: float) -> list[float]:
    """A unit vector in a plane: the cosine between two of them is cos(their angle difference)."""
    return [math.cos(math.radians(degrees)), math.sin(math.radians(degrees))]


ENTRIES = [
    IndexEntry("c-scam-1", "scam", "fake_prize"),
    IndexEntry("c-scam-2", "scam", "fake_prize"),
    IndexEntry("c-legit-1", "legit", None),
    IndexEntry("c-scam-3", "scam", "family_emergency"),
]
VECTORS = [at(0), at(10), at(20), at(90)]


async def test_neighbours_come_most_similar_first() -> None:
    index = InMemoryIndex(ENTRIES, VECTORS)

    neighbours = await index.nearest(at(4), 3)

    assert [n.id for n in neighbours] == ["c-scam-1", "c-scam-2", "c-legit-1"]
    assert neighbours[0].similarity == pytest.approx(math.cos(math.radians(4)))
    assert neighbours[0].modality == "fake_prize"


async def test_a_label_filter_finds_the_nearest_of_that_label() -> None:
    index = InMemoryIndex(ENTRIES, VECTORS)

    [legit] = await index.nearest(at(0), 1, label="legit")

    assert (legit.id, legit.label) == ("c-legit-1", "legit")


async def test_ties_break_by_id_and_k_can_exceed_the_index() -> None:
    index = InMemoryIndex(
        [IndexEntry("b", "scam", None), IndexEntry("a", "scam", None)], [at(0), at(0)]
    )

    neighbours = await index.nearest(at(0), 10)

    assert [n.id for n in neighbours] == ["a", "b"]


async def test_vectors_are_compared_by_direction_not_length() -> None:
    index = InMemoryIndex([IndexEntry("c", "scam", None)], [[3.0, 0.0]])

    [neighbour] = await index.nearest([0.5, 0.0], 1)

    assert neighbour.similarity == pytest.approx(1.0)


async def test_an_empty_index_has_no_neighbours() -> None:
    assert await InMemoryIndex([], []).nearest(at(0), 5) == []
    with pytest.raises(ValueError, match="one vector per index entry"):
        InMemoryIndex(ENTRIES, VECTORS[:2])
