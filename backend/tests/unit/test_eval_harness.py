from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import pytest

from esfake.corpus.dataset import CorpusRecord
from esfake.evaluation.harness import run_cases, split_cases
from esfake.pipeline.manifest import build_manifest, index_snapshot
from esfake.pipeline.redaction import REDACTOR_VERSION, Redactor
from esfake.pipeline.text import RawText, RedactedText
from esfake.pipeline.verdict import LLMUsage, Signal, Verdict
from esfake.pipeline.verifier import Pipeline
from esfake.shared.thresholds import PolicyV0Thresholds, load_thresholds
from tests.paths import CONFIG_DIR

POLICY = PolicyV0Thresholds(suspicious_at=1.0, likely_scam_at=3.0)


def record(case_id: str | None, split: str | None, text: str = "hola") -> CorpusRecord:
    return CorpusRecord.model_validate(
        {
            "case_id": case_id,
            "source": "curated_legit",
            "label": "legit",
            "subcategory": "easy",
            "text": text,
            "added_at": date(2026, 10, 7),
            "split": split,
        }
    )


class PrizeWord:
    def detect(self, message: RedactedText) -> Sequence[Signal]:
        if "premio" not in message.value:
            return []
        return [Signal(layer="rules", code="prize", weight=3.0, modality="fake_prize")]


class SeenText:
    """Records what the verifier receives, and answers as a judge served from the cache."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def verify(self, message: RedactedText) -> Verdict:
        self.texts.append(message.value)
        usage = LLMUsage(
            model="m",
            prompt_version="p1",
            input_tokens=10,
            output_tokens=2,
            cost_usd=Decimal("0.001"),
            cached=True,
        )
        return Verdict(
            level="suspicious", route="gray_zone", score=0, modality=None, signals=(), llm=usage
        )


def test_only_assigned_cases_of_the_split_are_evaluated() -> None:
    records = [record("a", "eval"), record("b", "test"), record(None, None), record("c", "index")]

    assert [r.case_id for r in split_cases(records, "eval")] == ["a"]


async def test_version_zero_has_no_detectors_and_finds_no_signals() -> None:
    predictions = await run_cases(
        [record("a", "eval", "Ganaste un premio")], Redactor(), Pipeline([], POLICY)
    )

    assert [(p.level, p.route, p.llm_used) for p in predictions] == [
        ("no_signals", "no_route", False)
    ]


async def test_detector_signals_reach_the_policy() -> None:
    pipeline = Pipeline([PrizeWord()], POLICY)

    verdict = await pipeline.verify(Redactor().redact(RawText("Ganaste un premio")))

    assert (verdict.level, verdict.modality) == ("likely_scam", "fake_prize")


async def test_cases_are_redacted_again_and_model_usage_is_recorded() -> None:
    verifier = SeenText()

    predictions = await run_cases(
        [record("a", "eval", "Llámame al 987654321")], Redactor(), verifier
    )

    assert verifier.texts == ["Llámame al [PHONE]"]
    assert predictions[0].llm_used
    assert not predictions[0].live_call
    assert predictions[0].cost_usd == Decimal("0.001")


async def test_cases_without_case_id_are_refused() -> None:
    with pytest.raises(ValueError, match="case_id"):
        await run_cases([record(None, "eval")], Redactor(), Pipeline([], POLICY))


def test_the_manifest_hash_changes_with_any_field() -> None:
    manifest = build_manifest(CONFIG_DIR, "abc123", ["c2", "c1"])
    other_commit = manifest.model_copy(update={"git_sha": "def456"})

    assert manifest.redactor_version == REDACTOR_VERSION
    assert manifest.thresholds_version == load_thresholds(CONFIG_DIR).version
    assert manifest.index_snapshot == index_snapshot(["c1", "c2"])
    assert len(manifest.hash) == 64
    assert manifest.hash == build_manifest(CONFIG_DIR, "abc123", ["c1", "c2"]).hash
    assert manifest.hash != other_commit.hash
