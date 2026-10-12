import re
import shutil
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

import esfake.cli._common
from esfake.cli.main import app
from esfake.corpus.dataset import CorpusRecord, DatasetInfo, Split, write_corpus, write_dataset_info
from esfake.corpus.validate import check_corpus
from tests.paths import CONFIG_DIR

runner = CliRunner()
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
INFO = DatasetInfo(dataset_version="1.0", cluster_threshold=0.9, embedding_model=MODEL)
MODALITIES = ("fake_prize", "family_emergency")


def record(n: int, split: Split, label: str = "scam", modality: str = "fake_prize") -> CorpusRecord:
    fields: dict[str, object] = (
        {"modality": modality} if label == "scam" else {"subcategory": "easy"}
    )
    return CorpusRecord.model_validate(
        {
            "case_id": f"c1:{n:064x}",
            "cluster_id": f"cl_{n}",
            "source": "public_alert" if label == "scam" else "curated_legit",
            "label": label,
            "text": f"mensaje, tema {n}",
            "added_at": date(2026, 10, 8),
            "split": split,
            "split_assigned_at": date(2026, 10, 8),
            **fields,
        }
    )


def complete() -> list[CorpusRecord]:
    """Each modality and the legitimate messages, with clusters in index, eval and test."""
    records, n = [], 0
    for group in (*MODALITIES, "legit"):
        for split in ("index", "eval", "test"):
            label = "legit" if group == "legit" else "scam"
            records.append(record(n, split, label, group if label == "scam" else "fake_prize"))
            n += 1
    return records


def check(records: list[CorpusRecord], info: DatasetInfo = INFO) -> tuple[list[str], list[str]]:
    report = check_corpus(
        records, info, threshold=0.9, embedding_model=MODEL, textual_modalities=MODALITIES
    )
    return report.problems, report.warnings


def test_a_complete_corpus_passes() -> None:
    assert check(complete()) == ([], [])


def test_unassigned_messages_fail_and_ask_for_assign() -> None:
    unassigned = complete()[0].model_copy(update={"split": None, "case_id": None})

    problems, _ = check([*complete()[1:], unassigned])

    assert any("esfake corpus assign" in p for p in problems)


def test_a_cluster_in_two_splits_fails() -> None:
    records = complete()
    records[1] = records[1].model_copy(update={"cluster_id": records[0].cluster_id})

    problems, _ = check(records)

    assert problems == ["clusters split across splits: ['cl_0']"]


def test_a_different_threshold_or_model_needs_a_new_major_version() -> None:
    problems, _ = check(complete(), INFO.model_copy(update={"cluster_threshold": 0.85}))

    assert "--new-major" in problems[0]


def test_every_textual_modality_needs_clusters_in_eval_and_test() -> None:
    records = [
        r for r in complete() if not (r.modality == "family_emergency" and r.split == "test")
    ]

    problems, _ = check(records)

    assert problems == ["modality family_emergency has no cluster in test: add messages"]


def test_missing_legitimate_messages_and_many_excluded_only_warn() -> None:
    records = [r for r in complete() if r.label == "scam"]
    records.append(record(99, "excluded"))

    problems, warnings = check(records)

    assert problems == []
    assert "no legitimate message in eval or test" in warnings[0]
    assert "excluded, over 5 %" in warnings[1]


class TopicEmbedder:
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        topics = [int(re.search(r"tema (\d+)", text)[1]) for text in texts]  # type: ignore[index]
        return [[1.0 if i == k else 0.0 for i in range(128)] for k in topics]


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, config)
    monkeypatch.setenv("ESFAKE_CONFIG_DIR", str(config))
    monkeypatch.setattr(esfake.cli._common, "local_embedder", TopicEmbedder)
    return config


def textual_corpus() -> list[CorpusRecord]:
    """Every textual modality of the real catalogue, plus legitimate messages, in every split."""
    modalities = [
        "family_emergency", "fake_prize", "bank_wallet_phishing", "whatsapp_code_theft",
        "fake_job_offer", "advance_fee_loan", "fake_online_sale",
    ]  # fmt: skip
    records, n = [], 0
    for group in (*modalities, None):
        for split in ("index", "eval", "test"):
            label = "scam" if group else "legit"
            records.append(record(n, split, label, group or "fake_prize"))
            n += 1
    return records


def run_validate(corpus: Path) -> tuple[int, str, str]:
    result = runner.invoke(app, ["corpus", "validate", "--corpus", str(corpus)])
    return result.exit_code, result.stdout, result.stderr


def test_validate_warns_and_passes_before_the_first_assignment(
    config: Path, tmp_path: Path
) -> None:
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, [record(1, "index").model_copy(update={"split": None})])

    code, _, stderr = run_validate(corpus)

    assert code == 0
    assert "not been assigned yet" in stderr


def test_validate_passes_a_clean_corpus_and_fails_on_a_leak(config: Path, tmp_path: Path) -> None:
    corpus = tmp_path / "corpus.jsonl"
    write_dataset_info(corpus, INFO)
    clean = textual_corpus()
    write_corpus(corpus, clean)
    passed = run_validate(corpus)
    # A test message that says the same as an index message ("tema 0") is a leak.
    leaked = clean[1].model_copy(update={"text": "mensaje, tema 0", "split": "test"})
    write_corpus(corpus, [*clean, leaked.model_copy(update={"case_id": f"c1:{999:064x}"})])
    failed = run_validate(corpus)

    assert passed[0] == 0, passed[2]
    assert "Corpus valid" in passed[1]
    assert failed[0] == 1
    assert f"leak: c1:{999:064x} has the index neighbour {clean[0].case_id}" in failed[2]
