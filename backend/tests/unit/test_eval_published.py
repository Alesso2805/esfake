import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

import esfake.cli.evaluation
import esfake.pipeline.redaction
from esfake.cli.main import app
from esfake.corpus.dataset import CorpusRecord, write_corpus
from esfake.evaluation.metrics import CasePrediction, compute_metrics
from esfake.evaluation.published import (
    latest_published,
    publish,
    published_versions,
    version_key,
)
from esfake.pipeline.manifest import build_manifest
from esfake.pipeline.redaction import Redactor
from tests.paths import CONFIG_DIR

runner = CliRunner()
TODAY = date(2026, 10, 8)


def scam(case_id: str) -> CasePrediction:
    return CasePrediction(
        case_id=case_id,
        label="scam",
        modality="fake_prize",
        level="likely_scam",
        route="early_exit",
    )


def corpus_with(tmp_path: Path, scams: int, legit: int = 1) -> Path:
    records = [
        CorpusRecord(
            case_id=f"s{i}",
            source="synthetic",
            label="scam",
            modality="fake_prize",
            text=f"Obsequio especial número {i}",
            added_at=TODAY,
            split="eval",
        )
        for i in range(scams)
    ] + [
        CorpusRecord(
            case_id=f"l{i}",
            source="curated_legit",
            label="legit",
            subcategory="bank_notification",
            text=f"Tu compra {i} fue aprobada",
            added_at=TODAY,
            split="eval",
        )
        for i in range(legit)
    ]
    path = tmp_path / "corpus.jsonl"
    write_corpus(path, records)
    return path


@pytest.fixture(autouse=True)
def no_spacy_and_a_clean_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(esfake.pipeline.redaction, "build_redactor", lambda _: Redactor())
    monkeypatch.setattr(esfake.cli.evaluation, "_git_sha", lambda: "abc123")


@pytest.mark.parametrize(
    ("version", "key"), [("v0", (0, 0)), ("v0.1", (0, 1)), ("v0.10", (0, 10)), ("v1.0", (1, 0))]
)
def test_versions_sort_by_number(version: str, key: tuple[int, int]) -> None:
    assert version_key(version) == key


@pytest.mark.parametrize("version", ["0", "v", "v01", "v1.0.1", "v1-rc"])
def test_malformed_versions_are_rejected(version: str) -> None:
    with pytest.raises(ValueError, match="not a version"):
        version_key(version)


def test_publishing_keeps_per_case_predictions_and_versions_only_move_forward(
    tmp_path: Path,
) -> None:
    manifest = build_manifest(CONFIG_DIR, "abc123", [])
    predictions = [scam("b"), scam("a")]
    metrics = compute_metrics(predictions)
    for version in ("v0", "v0.2", "v0.10"):
        publish(tmp_path, version, TODAY, manifest, metrics, predictions)

    latest = latest_published(tmp_path)

    assert published_versions(tmp_path) == ["v0", "v0.2", "v0.10"]
    assert latest is not None
    assert latest.version == "v0.10"
    assert [(c.case_id, c.level) for c in latest.predictions] == [
        ("a", "likely_scam"),
        ("b", "likely_scam"),
    ]
    assert latest.manifest_hash == manifest.hash
    assert latest.baseline().levels == {"a": "likely_scam", "b": "likely_scam"}
    with pytest.raises(ValueError, match="must come after"):
        publish(tmp_path, "v0.3", TODAY, manifest, metrics, predictions)


def test_eval_without_assigned_cases_warns_and_passes(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eval", "--corpus", str(tmp_path / "missing.jsonl")])

    assert result.exit_code == 0
    assert "no `eval` cases yet" in result.stderr


def test_eval_publishes_version_zero_then_compares_against_it(tmp_path: Path) -> None:
    corpus, evals = corpus_with(tmp_path, scams=2), tmp_path / "evals"
    options = ["--corpus", str(corpus), "--evals-dir", str(evals)]

    first = runner.invoke(app, ["eval", *options, "--publish", "v0"])
    second = runner.invoke(app, ["eval", *options])
    again = runner.invoke(app, ["eval", *options, "--publish", "v0"])

    assert first.exit_code == 0, first.output
    assert "No published version yet" in first.stdout
    assert "Published v0" in first.stdout
    published = json.loads((evals / "v0.json").read_text(encoding="utf-8"))
    assert published["manifest"]["git_sha"] == "abc123"
    assert {case["level"] for case in published["predictions"]} == {"no_signals"}
    assert "Obsequio" not in (evals / "v0.json").read_text(encoding="utf-8")
    assert second.exit_code == 0
    assert "Compared with v0 on 3 cases" in second.stdout
    assert again.exit_code == 1
    assert "must come after" in again.stderr


def test_eval_fails_on_a_significant_recall_regression(tmp_path: Path) -> None:
    # Version 0 of this fake history caught five scams that the current pipeline misses.
    evals = tmp_path / "evals"
    manifest = build_manifest(CONFIG_DIR, "old", [])
    caught = [scam(f"s{i}") for i in range(5)]
    publish(evals, "v0", TODAY, manifest, compute_metrics(caught), caught)

    result = runner.invoke(
        app, ["eval", "--corpus", str(corpus_with(tmp_path, scams=5)), "--evals-dir", str(evals)]
    )

    assert result.exit_code == 1
    assert "recall regressed against v0" in result.stdout
    assert "worse: s0 likely_scam -> no_signals" in result.stdout
    assert "Gate failed." in result.stdout


def test_publishing_needs_a_committed_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(esfake.cli.evaluation, "_git_sha", lambda: "abc123-dirty")
    corpus, evals = corpus_with(tmp_path, scams=1), tmp_path / "evals"

    result = runner.invoke(
        app, ["eval", "--corpus", str(corpus), "--evals-dir", str(evals), "--publish", "v0"]
    )

    assert result.exit_code == 1
    assert "commit every change" in result.stderr
    assert not evals.exists()


def test_eval_record_reports_what_it_recorded(tmp_path: Path) -> None:
    corpus = corpus_with(tmp_path, scams=1)

    result = runner.invoke(
        app,
        ["eval-record", "--corpus", str(corpus), "--evals-dir", str(tmp_path / "evals")],
    )

    assert result.exit_code == 0
    assert "(record)" in result.stdout
    assert "Recorded 0 responses live" in result.stdout
