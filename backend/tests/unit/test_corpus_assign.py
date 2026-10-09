import math
import random
import re
from collections import Counter
from datetime import date

import pytest

from esfake.corpus.assign import assign, case_id_for
from esfake.corpus.clusters import find_leaks
from esfake.corpus.dataset import CorpusRecord, Source, Split
from esfake.shared.hmac_keys import KeyRing

KEYS = KeyRing([("c1", "corpus-test-secret-1")])
TODAY = date(2026, 10, 8)
THRESHOLD = 0.9
DIMS = 64


def scam(text: str, modality: str = "fake_prize", source: Source = "public_alert") -> CorpusRecord:
    return CorpusRecord(source=source, label="scam", modality=modality, text=text, added_at=TODAY)


def legit(text: str, subcategory: str = "bank_notification") -> CorpusRecord:
    return CorpusRecord(
        source="curated_legit", label="legit", subcategory=subcategory, text=text, added_at=TODAY
    )


def placed(record: CorpusRecord, cluster_id: str, split: Split) -> CorpusRecord:
    return record.model_copy(
        update={
            "case_id": case_id_for(record, KEYS),
            "cluster_id": cluster_id,
            "split": split,
            "split_assigned_at": date(2026, 10, 1),
        }
    )


def topic(k: int) -> list[float]:
    return [1.0 if i == k else 0.0 for i in range(DIMS)]


def angle(degrees: float) -> list[float]:
    """A unit vector in the plane of the last two axes, apart from every topic()."""
    radians = math.radians(degrees)
    return [0.0] * (DIMS - 2) + [math.cos(radians), math.sin(radians)]


def splits_of(records: list[CorpusRecord]) -> Counter[str]:
    return Counter(str(r.split) for r in records)


def test_case_ids_are_hmacs_of_source_and_text_with_their_key_id() -> None:
    alert = scam("Ganaste un premio")
    synthetic = scam("Ganaste un premio", source="synthetic")

    assert re.fullmatch(r"c1:[0-9a-f]{64}", case_id_for(alert, KEYS))
    assert case_id_for(alert, KEYS) == case_id_for(alert, KEYS)
    assert case_id_for(alert, KEYS) != case_id_for(synthetic, KEYS)


def test_a_stratum_is_split_70_15_15_by_messages() -> None:
    records = [scam(f"premio {k}") for k in range(20)]

    result, report = assign(records, [topic(k) for k in range(20)], THRESHOLD, KEYS, TODAY)

    assert splits_of(result) == {"index": 14, "test": 3, "eval": 3}
    assert (report.new, report.new_clusters) == (20, 20)
    assert all(r.split_assigned_at == TODAY for r in result)


def test_a_stratum_with_three_clusters_gets_one_of_each() -> None:
    records = [scam(f"empleo {k}", "fake_job_offer") for k in range(3)]

    result, _ = assign(records, [topic(k) for k in range(3)], THRESHOLD, KEYS, TODAY)

    assert splits_of(result) == {"index": 1, "test": 1, "eval": 1}


def test_near_duplicates_share_cluster_and_split() -> None:
    records = [scam("premio A"), scam("premio A, versión 2"), scam("premio B")]

    result, report = assign(records, [topic(0), topic(0), topic(1)], THRESHOLD, KEYS, TODAY)

    assert result[0].cluster_id == result[1].cluster_id != result[2].cluster_id
    assert result[0].split == result[1].split
    assert report.new_clusters == 2


def test_assignment_is_deterministic_whatever_the_order_and_idempotent() -> None:
    records = [scam(f"premio {k}") for k in range(10)] + [legit(f"compra {k}") for k in range(10)]
    vectors = [topic(k) for k in range(20)]

    result, _ = assign(records, vectors, THRESHOLD, KEYS, TODAY)
    reversed_result, _ = assign(records[::-1], vectors[::-1], THRESHOLD, KEYS, TODAY)
    again, report = assign(result, vectors, THRESHOLD, KEYS, date(2027, 1, 1))

    assert {r.case_id: (r.cluster_id, r.split) for r in result} == {
        r.case_id: (r.cluster_id, r.split) for r in reversed_result
    }
    assert again == result
    assert report.new == 0


def test_a_new_message_inherits_the_frozen_split_of_its_cluster() -> None:
    first, _ = assign(
        [scam(f"premio {k}") for k in range(10)],
        [topic(k) for k in range(10)],
        THRESHOLD,
        KEYS,
        TODAY,
    )
    target = next(r for r in first if r.split == "eval")
    vectors = [topic(k) for k in range(10)]

    result, report = assign(
        [*first, scam("premio, otra variante")],
        [*vectors, vectors[first.index(target)]],
        THRESHOLD,
        KEYS,
        date(2026, 11, 1),
    )

    assert result[:10] == first
    assert (result[10].cluster_id, result[10].split) == (target.cluster_id, "eval")
    assert result[10].split_assigned_at == date(2026, 11, 1)
    assert report.inherited == 1


def test_a_message_that_bridges_clusters_of_different_splits_is_excluded() -> None:
    # 0 and 40 degrees are apart (cosine 0.77), but 20 degrees is near both (cosine 0.94).
    left, right = (
        placed(scam("premio A"), "cl_a", "index"),
        placed(scam("premio B"), "cl_b", "test"),
    )
    bridge, follower = scam("premio A o B"), scam("premio A o B, otra vez")

    result, report = assign(
        [left, right, bridge, follower],
        [angle(0), angle(40), angle(20), angle(20)],
        THRESHOLD,
        KEYS,
        TODAY,
    )

    assert [r.split for r in result] == ["index", "test", "excluded", "excluded"]
    assert result[2].cluster_id == result[3].cluster_id not in ("cl_a", "cl_b")
    assert report.excluded == 2


def test_a_synthetic_message_that_would_join_test_is_discarded() -> None:
    held_out = placed(scam("premio A"), "cl_a", "test")
    synthetic, real = scam("premio A bis", source="synthetic"), scam("premio A ter")

    result, report = assign([held_out, synthetic, real], [topic(0)] * 3, THRESHOLD, KEYS, TODAY)

    assert [r.text for r in result] == ["premio A", "premio A ter"]
    assert result[1].split == "test"
    assert report.discarded_synthetic == 1


def test_new_clusters_with_a_synthetic_member_never_go_to_test() -> None:
    records = [scam(f"premio {k}", source="synthetic") for k in range(20)]

    result, _ = assign(records, [topic(k) for k in range(20)], THRESHOLD, KEYS, TODAY)

    assert splits_of(result)["test"] == 0
    assert splits_of(result)["eval"] == 3


def test_new_clusters_fill_what_the_stratum_still_lacks() -> None:
    old = [placed(scam(f"premio {k}"), f"cl_{k}", "index") for k in range(17)]
    new = [scam(f"premio nuevo {k}") for k in range(3)]

    result, _ = assign([*old, *new], [topic(k) for k in range(20)], THRESHOLD, KEYS, TODAY)

    # 20 messages: 3 for test and 3 for eval, but only 3 new clusters to place.
    assert splits_of(result[17:]) == {"test": 2, "eval": 1}


def test_no_held_out_message_has_an_index_neighbour_over_the_threshold() -> None:
    rng = random.Random(7)  # noqa: S311 (test data, not cryptographic)
    bases = [[rng.gauss(0, 1) for _ in range(DIMS)] for _ in range(25)]
    vectors = [[x + rng.gauss(0, 0.15) for x in bases[i % 25]] for i in range(150)]
    records = [scam(f"mensaje {i}", f"modality_{i % 3}") for i in range(150)]

    result, _ = assign(records, vectors, THRESHOLD, KEYS, TODAY)

    assert {"index", "eval", "test"} <= set(splits_of(result))
    assert find_leaks(result, vectors, THRESHOLD) == []


def test_the_leak_check_finds_a_planted_leak() -> None:
    index, test = (
        placed(scam("premio A"), "cl_a", "index"),
        placed(scam("premio B"), "cl_b", "test"),
    )

    leaks = find_leaks([index, test], [topic(0), topic(0)], THRESHOLD)

    assert [(leak.held_out, leak.index) for leak in leaks] == [(test.case_id, index.case_id)]


@pytest.mark.parametrize("vectors", [[topic(0)], [topic(0)] * 3])
def test_inputs_must_line_up_and_case_ids_must_be_unique(vectors: list[list[float]]) -> None:
    records = [scam("premio"), scam("premio")]

    with pytest.raises(ValueError, match=r"one embedding per record|share a case_id"):
        assign(records, vectors if len(vectors) == 1 else vectors[:2], THRESHOLD, KEYS, TODAY)
