"""Calibration of k and delta on `eval` (ADR-0003 §6, EF-13 part c)."""

import math
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

import esfake.cli._common
from esfake.cli.main import app
from esfake.corpus.dataset import CorpusRecord, write_corpus
from esfake.evaluation.similarity_calibration import GridPoint, run_calibration
from esfake.pipeline.redaction import Redactor


def embed(texts: Sequence[str]) -> list[list[float]]:
    """'angulo 12.5' becomes the unit vector at 12.5 degrees."""
    degrees = [float(re.search(r"angulo ([0-9.]+)", t)[1]) for t in texts]  # type: ignore[index]
    return [[math.cos(math.radians(d)), math.sin(math.radians(d))] for d in degrees]


class AngleEmbedder:
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return embed(texts)


def record(case_id: str, degrees: float, label: str, split: str) -> CorpusRecord:
    kind = {"modality": "fake_prize"} if label == "scam" else {"subcategory": "easy"}
    return CorpusRecord.model_validate(
        {
            "case_id": case_id,
            "source": "synthetic" if label == "scam" else "curated_legit",
            "label": label,
            "text": f"mensaje angulo {degrees}",
            "added_at": date(2026, 10, 8),
            "split": split,
            **kind,
        }
    )


def corpus(path: Path) -> Path:
    # Index: scams from 0 to 8 degrees, legitimate messages from 30 to 34.
    index = [record(f"s{d}", d, "scam", "index") for d in (0, 2, 4, 6, 8)]
    index += [record(f"l{d}", d, "legit", "index") for d in (30, 32, 34)]
    cases = [
        record("e-scam-near", 3.1, "scam", "eval"),  # decided at every delta with k up to 5
        record("e-scam-mid", 10, "scam", "eval"),  # decided only with a small delta
        record("e-legit-13", 13, "legit", "eval"),  # raised with k = 3 and delta = 0.02
        record("e-legit-25", 25, "legit", "eval"),  # never raised
    ]
    write_corpus(path, [*index, *cases])
    return path


def point(grid: Sequence[GridPoint], k: int, delta: float) -> GridPoint:
    return next(p for p in grid if p.k == k and p.delta == delta)


def test_the_choice_decides_most_scams_without_raising_a_legitimate_case(tmp_path: Path) -> None:
    result = run_calibration(corpus(tmp_path / "corpus.jsonl"), Redactor, lambda: embed)

    assert result is not None
    assert (result.scams, result.legit, len(result.grid)) == (2, 2, 15)
    assert point(result.grid, 3, 0.02).legit_raised == 1  # a small delta lets a legit one in
    assert point(result.grid, 3, 0.04).scams_decided == 2
    assert point(result.grid, 7, 0.02).scams_decided == 0  # the 7th neighbour is legitimate
    # Three pairs decide both scams with no legitimate case; ties go to the larger delta, then k.
    assert result.choice == GridPoint(k=5, delta=0.04, scams_decided=2, legit_raised=0)


def test_without_splits_there_is_nothing_to_calibrate(tmp_path: Path) -> None:
    path = tmp_path / "corpus.jsonl"
    write_corpus(path, [record("s0", 0, "scam", "index")])

    assert run_calibration(path, Redactor, lambda: embed) is None


def test_the_command_prints_the_grid_and_the_recommendation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(esfake.cli._common, "local_embedder", lambda: AngleEmbedder())
    path = corpus(tmp_path / "corpus.jsonl")

    result = CliRunner().invoke(app, ["similarity", "calibrate", "--corpus", str(path)])

    assert result.exit_code == 0, result.output
    assert "Recommended: k = 5, delta = 0.04" in result.stdout
    assert "calibrated: true" in result.stdout
