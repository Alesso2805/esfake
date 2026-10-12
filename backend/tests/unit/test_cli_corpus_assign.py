import re
import shutil
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

import esfake.cli._common
from esfake.cli.main import app
from esfake.corpus.dataset import CorpusRecord, read_corpus, read_dataset_info, write_corpus
from tests.paths import CONFIG_DIR

runner = CliRunner()
KEY_VALUE = "corpus-test-key-0001"


class TopicEmbedder:
    """'tema 3' maps to the third axis: same topic, near-duplicates; other topics, unrelated."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        topics = [int(re.search(r"tema (\d+)", text)[1]) for text in texts]  # type: ignore[index]
        return [[1.0 if i == k else 0.0 for i in range(64)] for k in topics]


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


def set_cut(config: Path, threshold: str, reviewed: bool) -> None:
    path = config / "thresholds.yaml"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"cluster_threshold: [0-9.]+", f"cluster_threshold: {threshold}", text)
    text = re.sub(
        r"cluster_threshold_reviewed: \w+", f"cluster_threshold_reviewed: {reviewed}", text
    )
    path.write_text(text.replace("True", "true").replace("False", "false"), encoding="utf-8")


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, config)
    set_cut(config, "0.90", reviewed=True)
    monkeypatch.setenv("ESFAKE_CONFIG_DIR", str(config))
    monkeypatch.setenv("ESFAKE_CORPUS_HMAC_KEYS", f"c1:{KEY_VALUE}")
    monkeypatch.setattr(esfake.cli._common, "local_embedder", TopicEmbedder)
    return config


def run(corpus: Path, *options: str) -> tuple[int, str, str]:
    result = runner.invoke(app, ["corpus", "assign", "--corpus", str(corpus), *options])
    return result.exit_code, result.stdout, result.stderr


def test_assign_refuses_while_the_threshold_is_provisional(config: Path, tmp_path: Path) -> None:
    set_cut(config, "0.90", reviewed=False)
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, scams(1, 2))

    code, _, stderr = run(corpus)

    assert code == 1
    assert "still provisional" in stderr
    assert read_corpus(corpus)[0].split is None


def test_assign_needs_the_corpus_key(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ESFAKE_CORPUS_HMAC_KEYS", "c1:short")
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, scams(1))

    code, _, stderr = run(corpus)

    assert code == 1
    assert "ESFAKE_CORPUS_HMAC_KEYS" in stderr


def test_each_assignment_is_a_minor_version_and_splits_stay_frozen(
    config: Path, tmp_path: Path
) -> None:
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, scams(*range(10)))

    first = run(corpus)
    assigned = read_corpus(corpus)
    nothing = run(corpus)
    write_corpus(corpus, [*assigned, *scams(10, 3, variant=" otra vez")])
    second = run(corpus)

    assert first[0] == 0, first[2]
    assert "Dataset 1.0" in first[1]
    assert all(r.case_id and r.cluster_id and r.split for r in assigned)
    assert KEY_VALUE not in first[1] + first[2]
    assert "Nothing new to assign" in nothing[1]
    assert second[0] == 0
    assert "Dataset 1.1" in second[1]
    after = read_corpus(corpus)
    assert after[:10] == assigned
    assert after[11].split == assigned[3].split  # "tema 3" again joins its cluster
    info = read_dataset_info(corpus)
    assert info is not None
    assert (info.dataset_version, info.cluster_threshold) == ("1.1", 0.90)


def test_a_new_threshold_needs_a_new_major_version(config: Path, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, scams(*range(10)))
    run(corpus)
    case_ids = [r.case_id for r in read_corpus(corpus)]
    set_cut(config, "0.85", reviewed=True)
    write_corpus(corpus, [*read_corpus(corpus), *scams(11)])

    refused = run(corpus)
    major = run(corpus, "--new-major")

    assert refused[0] == 1
    assert "--new-major" in refused[2]
    assert major[0] == 0, major[2]
    assert "Dataset 2.0" in major[1]
    assert [r.case_id for r in read_corpus(corpus)][:10] == case_ids
