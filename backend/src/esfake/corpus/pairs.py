"""Pairs for the manual review that fixes the cluster threshold (ADR-0003 §6, EF-07).

`esfake corpus pairs` samples about 100 pairs across similarity bins around the likely cut and
writes them to a spreadsheet without their similarity, in a shuffled but deterministic order, so
the reviewer judges the texts and not the number. `esfake corpus threshold` recomputes each
pair's similarity and picks the cut that best agrees with the labels, preferring the lower cut
on ties, since grouping too much is safer than leaking near-duplicates across splits.
"""

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from esfake.corpus.dataset import CorpusRecord

FIELDS = ("pair_id", "same", "text_a", "text_b", "ref_a", "ref_b")
SAME = frozenset({"si", "sí", "s", "yes", "y", "1", "mismo", "same"})
DIFFERENT = frozenset({"no", "n", "0", "distinto", "different"})


@dataclass(frozen=True)
class ReviewPair:
    ref_a: str
    ref_b: str
    text_a: str
    text_b: str


@dataclass(frozen=True)
class LabeledPair:
    ref_a: str
    ref_b: str
    same: bool


@dataclass(frozen=True)
class ThresholdChoice:
    threshold: float
    f1: float
    accuracy: float
    pairs: int
    same: int


def record_ref(record: CorpusRecord) -> str:
    """Stable reference for a record before it has a case_id."""
    return hashlib.sha256(f"{record.source}\n{record.text}".encode()).hexdigest()[:12]


def _pair_key(ref_a: str, ref_b: str) -> str:
    return hashlib.sha256(f"{ref_a}:{ref_b}".encode()).hexdigest()


def select_review_pairs(
    records: list[CorpusRecord],
    similarities: NDArray[np.float64],
    *,
    low: float = 0.70,
    high: float = 0.98,
    bins: int = 10,
    per_bin: int = 10,
) -> list[ReviewPair]:
    refs = [record_ref(record) for record in records]
    rows, cols = np.triu_indices(len(records), k=1)
    values = similarities[rows, cols]
    inside = (values >= low) & (values < high)
    buckets: list[list[tuple[str, int, int]]] = [[] for _ in range(bins)]
    for i, j, value in zip(rows[inside], cols[inside], values[inside], strict=True):
        bucket = min(int((value - low) / (high - low) * bins), bins - 1)
        buckets[bucket].append((_pair_key(refs[i], refs[j]), int(i), int(j)))
    chosen = [item for bucket in buckets for item in sorted(bucket)[:per_bin]]
    return [
        ReviewPair(refs[i], refs[j], records[i].text, records[j].text) for _, i, j in sorted(chosen)
    ]


def write_pairs(path: Path, pairs: list[ReviewPair]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so spreadsheet programs show accents correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for number, pair in enumerate(pairs, start=1):
            writer.writerow(
                {
                    "pair_id": f"p{number:03d}",
                    "same": "",
                    "text_a": pair.text_a,
                    "text_b": pair.text_b,
                    "ref_a": pair.ref_a,
                    "ref_b": pair.ref_b,
                }
            )


def read_labeled_pairs(path: Path) -> list[LabeledPair]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    labeled, missing = [], []
    for row in rows:
        answer = (row.get("same") or "").strip().lower()
        if answer in SAME or answer in DIFFERENT:
            labeled.append(LabeledPair(row["ref_a"], row["ref_b"], answer in SAME))
        else:
            missing.append(row["pair_id"])
    if missing:
        raise ValueError(f"label every pair as 'si' or 'no'; missing: {', '.join(missing)}")
    return labeled


def choose_threshold(scored: list[tuple[float, bool]]) -> ThresholdChoice:
    """Best F1 for "same" when grouping pairs at or above the cut; ties keep the lower cut."""
    same_total = sum(1 for _, same in scored if same)
    if same_total == 0:
        raise ValueError("no pair is labelled 'same'; review pairs with higher similarity")
    best: ThresholdChoice | None = None
    for cut in sorted({similarity for similarity, _ in scored}):
        true_pos = sum(1 for s, same in scored if s >= cut and same)
        false_pos = sum(1 for s, same in scored if s >= cut and not same)
        false_neg = same_total - true_pos
        f1 = 2 * true_pos / (2 * true_pos + false_pos + false_neg)
        accuracy = (len(scored) - false_pos - false_neg) / len(scored)
        if best is None or f1 > best.f1:
            best = ThresholdChoice(round(cut, 4), f1, accuracy, len(scored), same_total)
    if best is None:
        raise ValueError("no labelled pairs to score")
    return best
