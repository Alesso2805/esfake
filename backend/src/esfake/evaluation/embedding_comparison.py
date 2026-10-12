"""The EF-07 embedding checkpoint: the deployed model against the contender (ADR-0003, amendment 1).

Both models score the same labelled pairs. The contender replaces the deployed model only if the
95 % paired bootstrap lower bound of AUC(contender) - AUC(deployed) is above 0 and its p95
latency per message fits the 200 ms budget of the similarity layer.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from pydantic import BaseModel, ConfigDict

from esfake.corpus.pairs import choose_threshold
from esfake.evaluation.stats import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, percentile

LATENCY_BUDGET_MS = 200.0  # docs/SPEC.md, similarity layer
LONG_MESSAGE_TOKENS = (128, 512)  # MiniLM's training length and e5's window


def roc_auc(scores: Sequence[float], labels: Sequence[bool]) -> float:
    """Chance that a random "same" pair scores above a random "different" one; ties count half."""
    values, same = np.asarray(scores, dtype=np.float64), np.asarray(labels, dtype=bool)
    positives, negatives = int(same.sum()), int((~same).sum())
    if not positives or not negatives:
        raise ValueError("the AUC needs pairs labelled both 'same' and 'different'")
    order = np.argsort(values, kind="mergesort")
    _, inverse, counts = np.unique(values[order], return_inverse=True, return_counts=True)
    average_rank = np.cumsum(counts) - (counts - 1) / 2  # 1-based, ties share their mean rank
    ranks = np.empty(len(values))
    ranks[order] = average_rank[inverse]
    return float((ranks[same].sum() - positives * (positives + 1) / 2) / (positives * negatives))


class AucDifference(BaseModel):
    """AUC(contender) - AUC(deployed) on the same pairs, with a paired bootstrap interval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    difference: float
    low: float
    high: float
    resamples: int
    seed: int


def auc_difference(
    contender: Sequence[float],
    deployed: Sequence[float],
    labels: Sequence[bool],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> AucDifference:
    n = len(labels)
    # Not cryptographic: a seeded generator makes the published interval reproducible.
    rng = random.Random(seed)  # noqa: S311
    estimates: list[float] = []
    while len(estimates) < resamples:
        picked = rng.choices(range(n), k=n)
        sample = [labels[i] for i in picked]
        if all(sample) or not any(sample):
            continue  # a resample without both labels has no AUC; draw again
        estimates.append(
            roc_auc([contender[i] for i in picked], sample)
            - roc_auc([deployed[i] for i in picked], sample)
        )
    return AucDifference(
        difference=roc_auc(contender, labels) - roc_auc(deployed, labels),
        low=percentile(estimates, 0.025),
        high=percentile(estimates, 0.975),
        resamples=resamples,
        seed=seed,
    )


@dataclass(frozen=True)
class ModelMeasures:
    """What one model produced: a cosine per labelled pair, latencies and corpus token counts."""

    name: str
    scores: list[float]
    latencies_ms: list[float]
    token_counts: list[int]
    max_tokens: int


class ModelSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    auc: float
    threshold: float
    f1: float
    agreement: float
    latency_ms_p95: float
    max_tokens: int
    share_over: dict[int, float]


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    measured_at: date
    pairs: int
    same: int
    deployed: ModelSummary
    contender: ModelSummary
    auc_difference: AucDifference
    switch: bool
    reasons: list[str]


def _summary(measures: ModelMeasures, labels: Sequence[bool]) -> ModelSummary:
    choice = choose_threshold(list(zip(measures.scores, labels, strict=True)))
    counts = measures.token_counts
    return ModelSummary(
        name=measures.name,
        auc=roc_auc(measures.scores, labels),
        threshold=choice.threshold,
        f1=choice.f1,
        agreement=choice.accuracy,
        latency_ms_p95=percentile(measures.latencies_ms, 0.95),
        max_tokens=measures.max_tokens,
        share_over={
            limit: sum(c > limit for c in counts) / len(counts) if counts else 0.0
            for limit in LONG_MESSAGE_TOKENS
        },
    )


def compare(
    deployed: ModelMeasures,
    contender: ModelMeasures,
    labels: Sequence[bool],
    measured_at: date,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
) -> Comparison:
    first, second = _summary(deployed, labels), _summary(contender, labels)
    difference = auc_difference(contender.scores, deployed.scores, labels, resamples=resamples)
    reasons = []
    if difference.low <= 0:
        reasons.append(f"the AUC gain's 95 % lower bound is {difference.low:+.3f}, not above 0")
    if second.latency_ms_p95 > LATENCY_BUDGET_MS:
        reasons.append(
            f"p95 latency {second.latency_ms_p95:.0f} ms exceeds the "
            f"{LATENCY_BUDGET_MS:.0f} ms budget"
        )
    return Comparison(
        measured_at=measured_at,
        pairs=len(labels),
        same=sum(labels),
        deployed=first,
        contender=second,
        auc_difference=difference,
        switch=not reasons,
        reasons=reasons or ["the AUC gain is above 0 at 95 % and latency fits the budget"],
    )
