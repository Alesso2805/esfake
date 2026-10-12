from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from esfake.corpus.dataset import CorpusRecord, write_corpus
from esfake.evaluation.run import EvaluationRequest, EvaluationResult, run_evaluation
from esfake.pipeline.redaction import Redactor
from esfake.shared.clock import FakeClock
from tests.paths import CONFIG_DIR

CLOCK = FakeClock(datetime(2026, 10, 12, tzinfo=UTC))


def write_eval_corpus(path: Path, *, with_cases: bool = True) -> Path:
    records = [
        CorpusRecord(
            case_id="s1",
            source="synthetic",
            label="scam",
            modality="fake_prize",
            text="Obsequio especial uno",
            added_at=date(2026, 10, 8),
            split="eval" if with_cases else "index",
        )
    ]
    write_corpus(path, records)
    return path


def run(tmp_path: Path, *, with_cases: bool = True, **options: object) -> EvaluationResult:
    request = EvaluationRequest(
        mode="cached_strict",
        corpus=write_eval_corpus(tmp_path / "corpus.jsonl", with_cases=with_cases),
        evals_dir=tmp_path / "evals",
        llm_cache=tmp_path / "cache",
        config_dir=CONFIG_DIR,
        git_sha="abc123",
        **options,  # type: ignore[arg-type]
    )
    return run_evaluation(request, Redactor, CLOCK)


def test_a_corpus_without_eval_cases_is_not_an_error(tmp_path: Path) -> None:
    result = run(tmp_path, with_cases=False)

    assert result.status == "no_cases"
    assert result.error is not None
    assert "no `eval` cases" in result.error
    assert result.report is None


def test_a_clean_run_reports_and_publishes_nothing_unless_asked(tmp_path: Path) -> None:
    result = run(tmp_path)

    assert (result.status, result.published_path) == ("ok", None)
    assert result.report is not None
    assert not (tmp_path / "evals").exists()


def test_record_mode_adds_what_was_recorded(tmp_path: Path) -> None:
    request = EvaluationRequest(
        "record",
        write_eval_corpus(tmp_path / "corpus.jsonl"),
        tmp_path / "evals",
        tmp_path / "cache",
        CONFIG_DIR,
        "abc123",
        budget_usd=Decimal("5"),
    )

    result = run_evaluation(request, Redactor, CLOCK)

    assert result.note is not None
    assert result.note.startswith("Recorded 0 responses live")


def test_publishing_writes_the_version_with_the_injected_date(tmp_path: Path) -> None:
    result = run(tmp_path, publish_as="v0")

    assert result.status == "ok"
    assert result.published_path == tmp_path / "evals" / "v0.json"
    assert "2026-10-12" in result.published_path.read_text(encoding="utf-8")


def test_publishing_from_a_dirty_tree_is_refused(tmp_path: Path) -> None:
    request = EvaluationRequest(
        "cached_strict",
        write_eval_corpus(tmp_path / "corpus.jsonl"),
        tmp_path / "evals",
        tmp_path / "cache",
        CONFIG_DIR,
        "abc123-dirty",
        publish_as="v0",
    )

    result = run_evaluation(request, Redactor, CLOCK)

    assert result.status == "publish_refused"
    assert result.error is not None
    assert "commit every change" in result.error
    assert not (tmp_path / "evals").exists()


def test_a_second_publish_of_the_same_version_is_refused(tmp_path: Path) -> None:
    run(tmp_path, publish_as="v0")

    result = run(tmp_path, publish_as="v0")

    assert result.status == "publish_refused"
    assert result.error is not None
    assert "must come after" in result.error
