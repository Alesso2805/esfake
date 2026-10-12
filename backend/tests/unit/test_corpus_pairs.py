import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from esfake.corpus.clusters import cosine_matrix
from esfake.corpus.dataset import CorpusRecord
from esfake.corpus.pairs import (
    ReviewPair,
    choose_threshold,
    matched_range,
    merge_pairs,
    read_labeled_pairs,
    record_ref,
    select_review_pairs,
    write_pairs,
)
from esfake.pipeline.similarity.embedder import _register
from esfake.shared.models_config import load_models_config
from tests.paths import CONFIG_DIR


def _record(text: str) -> CorpusRecord:
    return CorpusRecord(
        source="synthetic",
        label="scam",
        modality="family_emergency",
        text=text,
        added_at=date(2026, 10, 7),
    )


def _vectors_at(angles_degrees: list[float]) -> list[list[float]]:
    """2-D unit vectors; the cosine between two of them is cos(angle difference)."""
    return [[math.cos(math.radians(a)), math.sin(math.radians(a))] for a in angles_degrees]


def test_cosine_matrix_handles_parallel_orthogonal_and_zero_vectors() -> None:
    similarities = cosine_matrix([[1.0, 0.0], [2.0, 0.0], [0.0, 3.0], [0.0, 0.0]])

    assert similarities[0, 1] == pytest.approx(1.0)
    assert similarities[0, 2] == pytest.approx(0.0)
    assert similarities[0, 3] == pytest.approx(0.0)


def test_review_pairs_stay_in_range_cap_each_bin_and_hide_the_order_of_similarity() -> None:
    angles = [index * 3.0 for index in range(30)]  # pairwise cosines from 1.0 down to ~0
    records = [_record(f"mensaje {index}") for index in range(len(angles))]
    similarities = cosine_matrix(_vectors_at(angles))

    pairs = select_review_pairs(records, similarities, low=0.70, high=0.98, bins=4, per_bin=3)
    again = select_review_pairs(records, similarities, low=0.70, high=0.98, bins=4, per_bin=3)

    refs = {record_ref(r): i for i, r in enumerate(records)}
    values = [float(similarities[refs[p.ref_a], refs[p.ref_b]]) for p in pairs]
    assert pairs == again
    assert len(pairs) == 12
    assert all(0.70 <= value < 0.98 for value in values)
    assert values != sorted(values)


def test_labelled_pairs_round_trip_and_accept_spanish_answers(tmp_path: Path) -> None:
    path = tmp_path / "pairs.csv"
    write_pairs(
        path, [ReviewPair("a", "b", "Hola mamá", "Hola má"), ReviewPair("a", "c", "x", "y")]
    )
    content = path.read_text(encoding="utf-8-sig").replace("p001,,", "p001,Sí,")
    path.write_text(content.replace("p002,,", "p002,NO,"), encoding="utf-8-sig")

    labeled = read_labeled_pairs(path)

    assert [(p.ref_a, p.ref_b, p.same) for p in labeled] == [("a", "b", True), ("a", "c", False)]


def test_every_pair_must_be_labelled(tmp_path: Path) -> None:
    path = tmp_path / "pairs.csv"
    write_pairs(path, [ReviewPair("a", "b", "x", "y")])

    with pytest.raises(ValueError, match="missing: p001"):
        read_labeled_pairs(path)


def test_threshold_maximises_agreement_and_prefers_the_lower_cut_on_ties() -> None:
    scored = [(0.97, True), (0.93, True), (0.90, True), (0.88, False), (0.80, False)]

    assert choose_threshold(scored).threshold == 0.90
    # 0.86 and 0.90 separate these equally well; the lower cut groups more, which is safer.
    tied = [(0.95, True), (0.90, True), (0.86, True), (0.84, False)]
    assert choose_threshold(tied).threshold == 0.86


def test_threshold_needs_at_least_one_same_pair() -> None:
    with pytest.raises(ValueError, match="no pair is labelled 'same'"):
        choose_threshold([(0.9, False)])


def test_embeddings_order_does_not_change_the_matrix() -> None:
    vectors = np.array(_vectors_at([0.0, 10.0, 20.0]))
    forward = cosine_matrix(vectors.tolist())
    backward = cosine_matrix(vectors[::-1].tolist())

    assert forward[0, 2] == pytest.approx(backward[2, 0])


def test_the_contender_range_covers_the_same_pairs_by_rank() -> None:
    reference = cosine_matrix(_vectors_at([0, 5, 12, 30, 60, 90]))
    # Same ranking on another scale, as e5 rates every pair higher than MiniLM does.
    other = 0.8 + 0.2 * reference
    rows, cols = np.triu_indices(6, k=1)

    low, high = matched_range(reference, other, 0.9, 0.999)

    inside_reference = (reference[rows, cols] >= 0.9) & (reference[rows, cols] < 0.999)
    inside_other = (other[rows, cols] >= low) & (other[rows, cols] < high)
    assert inside_reference.tolist() == inside_other.tolist()
    assert low > 0.9


def test_merged_pairs_have_no_repeats_and_a_stable_order() -> None:
    a = ReviewPair("r1", "r2", "uno", "dos")
    b = ReviewPair("r1", "r3", "uno", "tres")

    assert merge_pairs([a, b], [b]) == merge_pairs([b], [a]) == merge_pairs([b, a])
    assert len(merge_pairs([a, b], [b])) == 2


def test_the_contender_is_configured_with_its_prefix_and_onnx_source() -> None:
    contender = load_models_config(CONFIG_DIR).embedding_contender

    assert contender is not None
    assert contender.name == "intfloat/multilingual-e5-small"
    assert contender.prefix == "query: "
    assert contender.onnx is not None
    assert contender.onnx.model_file == "onnx/model.onnx"
    _register(contender)
    _register(contender)  # once per process: a second call is a no-op
