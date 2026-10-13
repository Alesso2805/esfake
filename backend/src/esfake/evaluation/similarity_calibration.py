"""Calibrate k and delta of the similarity layer on `eval` (ADR-0003 §6, EF-13).

A grid search over k in {3, 5, 7} and delta in {0.02, ..., 0.10}: the pair that decides the most
scam cases while raising no legitimate one, ties going to the larger delta and then to the larger
k, the more cautious choice. It applies the layer's own rule (`similarity.detector.decides`) and
follows the path of an evaluation: each case goes through normalisation and the redactor before
it is embedded.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from esfake.corpus.dataset import CorpusRecord, read_corpus
from esfake.evaluation.harness import memory_index, split_cases
from esfake.pipeline.normalize import normalize
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.similarity.detector import Embed, decides
from esfake.pipeline.similarity.index import SimilarityIndex
from esfake.pipeline.text import RawText

GRID_K = (3, 5, 7)
GRID_DELTA = (0.02, 0.04, 0.06, 0.08, 0.10)


@dataclass(frozen=True)
class GridPoint:
    k: int
    delta: float
    scams_decided: int
    legit_raised: int


@dataclass(frozen=True)
class Calibration:
    scams: int
    legit: int
    grid: tuple[GridPoint, ...]
    choice: GridPoint | None  # None: every pair raises a legitimate case


async def calibrate(
    cases: Sequence[CorpusRecord], index: SimilarityIndex, embed: Embed, redactor: Redactor
) -> Calibration:
    vectors = embed([redactor.redact(normalize(RawText(case.text))).value for case in cases])
    outcomes = []
    for case, vector in zip(cases, vectors, strict=True):
        nearest = await index.nearest(vector, max(GRID_K))
        legit = await index.nearest(vector, 1, label="legit")
        outcomes.append((case.label, nearest, legit[0] if legit else None))
    grid = []
    for k in GRID_K:
        for delta in GRID_DELTA:
            decided = [
                label for label, nearest, legit in outcomes if decides(nearest, legit, k, delta)
            ]
            grid.append(GridPoint(k, delta, decided.count("scam"), decided.count("legit")))
    eligible = [point for point in grid if point.legit_raised == 0]
    return Calibration(
        scams=sum(case.label == "scam" for case in cases),
        legit=sum(case.label == "legit" for case in cases),
        grid=tuple(grid),
        choice=max(eligible, key=lambda p: (p.scams_decided, p.delta, p.k), default=None),
    )


def run_calibration(
    corpus: Path, make_redactor: Callable[[], Redactor], make_embed: Callable[[], Embed]
) -> Calibration | None:
    """None when the corpus has no `eval` or no `index` split yet (EF-07)."""
    records = read_corpus(corpus)
    cases = split_cases(records, "eval")
    index_records = split_cases(records, "index")
    if not cases or not index_records:
        return None
    embed = make_embed()
    return asyncio.run(calibrate(cases, memory_index(index_records, embed), embed, make_redactor()))
