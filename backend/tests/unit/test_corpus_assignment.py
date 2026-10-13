"""The `corpus assign` service, without the CLI (docs/ARCHITECTURE_RULES.md, rule 4)."""

import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from esfake.corpus.assignment import AssignmentRequest, AssignmentResult, run_assignment
from esfake.corpus.dataset import CorpusRecord, read_corpus, read_dataset_info, write_corpus
from esfake.shared.clock import FakeClock
from esfake.shared.hmac_keys import KeyRing
from tests.paths import CONFIG_DIR

CLOCK = FakeClock(datetime(2026, 10, 12, 9, 0, tzinfo=UTC))
KEYS = KeyRing([("c1", "corpus-test-key-0001")])


def scams(*topics: int, variant: str = "") -> list[CorpusRecord]:
    return [
        CorpusRecord(
            source="public_alert",
            label="scam",
            modality="fake_prize",
            text=f"Ganaste{variant}, tema {k}",
            added_at=date(2026, 10, 8),
        )
        for k in topics
    ]


def embed(texts: list[str]) -> list[list[float]]:
    """'tema 3' maps to axis 3: same topic, near-duplicates; other topics, unrelated."""
    topics = [int(re.search(r"tema (\d+)", text)[1]) for text in texts]  # type: ignore[index]
    return [[1.0 if i == k else 0.0 for i in range(64)] for k in topics]


def set_cut(config: Path, threshold: str, *, reviewed: bool) -> None:
    path = config / "thresholds.yaml"
    text = re.sub(
        r"cluster_threshold: [0-9.]+",
        f"cluster_threshold: {threshold}",
        path.read_text(encoding="utf-8"),
    )
    text = re.sub(
        r"cluster_threshold_reviewed: \w+",
        f"cluster_threshold_reviewed: {str(reviewed).lower()}",
        text,
    )
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def config(tmp_path: Path) -> Path:
    config = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, config)
    set_cut(config, "0.90", reviewed=True)
    return config


def run(corpus: Path, config: Path, *, new_major: bool = False) -> AssignmentResult:
    return run_assignment(AssignmentRequest(corpus, config, new_major), lambda: KEYS, embed, CLOCK)


def test_a_provisional_threshold_refuses_before_touching_anything(
    config: Path, tmp_path: Path
) -> None:
    set_cut(config, "0.90", reviewed=False)
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, scams(1, 2))

    result = run(corpus, config)

    assert result.status == "refused"
    assert result.error is not None
    assert "still provisional" in result.error
    assert read_corpus(corpus)[0].split is None


def test_keys_and_embeddings_are_only_asked_for_when_something_is_new(
    config: Path, tmp_path: Path
) -> None:
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, scams(*range(5)))
    run(corpus, config)

    def no_keys() -> KeyRing:
        raise AssertionError("keys were asked for with nothing to assign")

    def no_model(texts: list[str]) -> list[list[float]]:
        raise AssertionError("the model was loaded with nothing to assign")

    result = run_assignment(AssignmentRequest(corpus, config), no_keys, no_model, CLOCK)

    assert result.status == "nothing_new"


def test_a_missing_key_ring_refuses_with_its_message(config: Path, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, scams(1))

    def missing() -> KeyRing:
        raise ValueError("set ESFAKE_CORPUS_HMAC_KEYS")

    result = run_assignment(AssignmentRequest(corpus, config), missing, embed, CLOCK)

    assert (result.status, result.error) == ("refused", "set ESFAKE_CORPUS_HMAC_KEYS")


def test_assignments_are_minor_versions_dated_by_the_clock(config: Path, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, scams(*range(10)))

    first = run(corpus, config)
    write_corpus(corpus, [*read_corpus(corpus), *scams(10, 3, variant=" otra vez")])
    second = run(corpus, config)

    assert (first.status, second.status) == ("assigned", "assigned")
    assert first.info is not None
    assert second.info is not None
    assert (first.info.dataset_version, second.info.dataset_version) == ("1.0", "1.1")
    assert second.report is not None
    assert second.report.inherited == 1  # "tema 3" again joins its cluster
    assert {r.split_assigned_at for r in read_corpus(corpus)} == {date(2026, 10, 12)}
    info = read_dataset_info(corpus)
    assert info is not None
    assert info.dataset_version == "1.1"
    assert (second.total, second.threshold_needs_review) == (12, False)


def test_a_new_threshold_needs_a_new_major_version(config: Path, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, scams(*range(10)))
    run(corpus, config)
    set_cut(config, "0.85", reviewed=True)
    write_corpus(corpus, [*read_corpus(corpus), *scams(11)])

    refused = run(corpus, config)
    major = run(corpus, config, new_major=True)

    assert refused.status == "refused"
    assert refused.error is not None
    assert "--new-major" in refused.error
    assert major.info is not None
    assert major.info.dataset_version == "2.0"


def test_the_threshold_needs_review_above_five_percent_excluded() -> None:
    assert AssignmentResult("assigned", excluded=6, total=100).threshold_needs_review
    assert not AssignmentResult("assigned", excluded=5, total=100).threshold_needs_review
    assert not AssignmentResult("nothing_new").threshold_needs_review
