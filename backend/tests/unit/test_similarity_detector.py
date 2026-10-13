"""The similarity layer (EF-13): decides with k and delta, only raises, keeps its neighbours."""

import math
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from esfake.corpus.dataset import CorpusRecord, write_corpus
from esfake.evaluation.run import EvaluationRequest, run_evaluation
from esfake.pipeline.llm.cache import ResponseCache
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.similarity.detector import SimilarityDetector
from esfake.pipeline.similarity.index import IndexEntry, InMemoryIndex, NeighborLabel
from esfake.pipeline.text import RedactedText
from esfake.pipeline.verifier import build_pipeline
from esfake.shared.clock import FakeClock
from esfake.shared.thresholds import SimilarityThresholds, load_thresholds
from tests.paths import CONFIG_DIR

THRESHOLDS = SimilarityThresholds(k=3, delta=0.05, calibrated=False, weight=3.0)
type Entry = tuple[float, NeighborLabel, str | None]
PRIZE: tuple[Entry, ...] = ((0, "scam", "fake_prize"), (2, "scam", "fake_prize"))
FAR_LEGIT: Entry = (40, "legit", None)


def at(degrees: float) -> list[float]:
    return [math.cos(math.radians(degrees)), math.sin(math.radians(degrees))]


def embed(texts: list[str]) -> list[list[float]]:
    """'angulo 12.5' becomes the unit vector at 12.5 degrees."""
    return [at(float(re.search(r"angulo ([0-9.]+)", t)[1])) for t in texts]  # type: ignore[index]


def index(*entries: Entry) -> InMemoryIndex:
    return InMemoryIndex(
        [IndexEntry(f"c{n}", label, modality) for n, (_, label, modality) in enumerate(entries)],
        [at(degrees) for degrees, _, _ in entries],
    )


async def detect(entries: InMemoryIndex, degrees: float) -> list[object]:
    detector = SimilarityDetector(embed, entries, THRESHOLDS)
    return list(await detector.detect(RedactedText(f"angulo {degrees}")))


async def test_k_scam_neighbours_clear_of_the_legit_one_decide() -> None:
    entries = index(*PRIZE, (4, "scam", "fake_prize"), FAR_LEGIT)
    detector = SimilarityDetector(embed, entries, THRESHOLDS)

    [signal] = await detector.detect(RedactedText("angulo 1.2"))

    assert (signal.layer, signal.code, signal.weight) == ("similarity", "similar_known_scam", 3.0)
    assert signal.modality == "fake_prize"
    assert signal.neighbor_ids == ("c1", "c0", "c2")  # most similar first


@pytest.mark.parametrize(
    ("entries", "reason"),
    [
        ((*PRIZE, (3, "legit", None)), "a legit neighbour among the k"),
        ((*PRIZE, (20, "scam", "fake_prize"), (22, "legit", None)), "the legit one within delta"),
        (PRIZE, "fewer than k"),
        ((), "an empty index"),
    ],
)
async def test_nothing_is_raised_without_a_clear_scam_majority(
    entries: tuple[Entry, ...], reason: str
) -> None:
    assert await detect(index(*entries), 1.2) == [], reason


async def test_neighbours_that_disagree_on_modality_give_none() -> None:
    entries = index(PRIZE[0], (2, "scam", "family_emergency"), (4, "scam", "fake_prize"))
    detector = SimilarityDetector(embed, entries, THRESHOLDS)

    [signal] = await detector.detect(RedactedText("angulo 1.2"))

    assert signal.modality is None


async def test_similarity_raises_a_verdict_in_the_pipeline_and_never_lowers_it(
    tmp_path: Path,
) -> None:
    entries = index(*PRIZE, (4, "scam", "fake_prize"), FAR_LEGIT)
    detector = SimilarityDetector(embed, entries, THRESHOLDS)
    pipeline = build_pipeline(CONFIG_DIR, ResponseCache(tmp_path, "cached_strict"), detector)

    near = await pipeline.verify(RedactedText("hola, angulo 1.2"))
    far = await pipeline.verify(RedactedText("hola, angulo 60"))

    assert (near.level, near.modality) == ("likely_scam", "fake_prize")
    assert far.level == "no_signals"  # no decision: nothing added, nothing taken away
    assert all(signal.weight > 0 for signal in near.signals)


def test_the_provisional_values_live_in_thresholds_yaml() -> None:
    similarity = load_thresholds(CONFIG_DIR).similarity

    assert (similarity.k, similarity.delta, similarity.calibrated) == (5, 0.05, False)
    assert similarity.weight == 3.0


def eval_corpus(path: Path) -> Path:
    def record(case_id: str, degrees: float, split: str) -> CorpusRecord:
        return CorpusRecord.model_validate(
            {
                "case_id": case_id,
                "source": "synthetic",
                "label": "scam",
                "modality": "fake_prize",
                "text": f"Obsequio angulo {degrees}",
                "added_at": date(2026, 10, 8),
                "split": split,
            }
        )

    records = [record(f"i{n}", degrees, "index") for n, degrees in enumerate((0, 2, 4, 6, 8))]
    write_corpus(path, [*records, record("e1", 3.1, "eval")])
    return path


@pytest.mark.parametrize(("with_model", "recall"), [(True, "(1/1)"), (False, "(0/1)")])
def test_evaluation_searches_the_index_split_when_it_has_the_model(
    tmp_path: Path, with_model: bool, recall: str
) -> None:
    request = EvaluationRequest(
        mode="cached_strict",
        corpus=eval_corpus(tmp_path / "corpus.jsonl"),
        evals_dir=tmp_path / "evals",
        llm_cache=tmp_path / "cache",
        config_dir=CONFIG_DIR,
        git_sha="abc123",
    )
    clock = FakeClock(datetime(2026, 10, 12, tzinfo=UTC))

    result = run_evaluation(
        request, Redactor, clock, make_embed=(lambda: embed) if with_model else None
    )

    assert result.report is not None
    recall_line = next(line for line in result.report.splitlines() if line.startswith("Recall:"))
    assert recall_line.endswith(recall)
