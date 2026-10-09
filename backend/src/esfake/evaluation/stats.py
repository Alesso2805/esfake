"""Statistics shared by every evaluation."""

import math
import random
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

Z_95 = 1.959963984540054

# ADR-0006 A: 10 000 resamples with a fixed seed, recorded in the evaluation file.
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261006


def wilson_interval(successes: int, trials: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a proportion (95 % by default)."""
    if trials == 0:
        return 0.0, 1.0
    p = successes / trials
    denominator = 1 + z**2 / trials
    centre = (p + z**2 / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)


def percentile(values: Sequence[float], q: float) -> float:
    """Percentile with linear interpolation between the closest ranks (q in [0, 1])."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    below = math.floor(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)


def mcnemar_one_sided(worse: int, better: int) -> float:
    """Exact one-sided McNemar p-value that a change made an outcome worse (ADR-0006 B).

    `worse` counts the discordant cases the new version gets wrong and the old one right, and
    `better` the reverse. Under the null hypothesis each discordant case goes either way with
    probability 1/2, so the p-value is P(X >= worse) for X ~ Binomial(worse + better, 1/2).
    """
    n = worse + better
    tail = sum(math.comb(n, k) for k in range(worse, n + 1))
    return tail / (1 << n)


class PairedDifference(BaseModel):
    """Difference of two paired proportions, a - b, with a bootstrap percentile interval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cases: int
    difference: float
    low: float
    high: float
    resamples: int
    seed: int


def paired_bootstrap(
    pairs: Sequence[tuple[bool, bool]],
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    confidence: float = 0.95,
) -> PairedDifference:
    """Percentile interval for proportion(a) - proportion(b) over the same cases (ADR-0006 A).

    Cases are resampled with replacement, keeping both systems' outcomes for a case together.
    """
    if not pairs:
        raise ValueError("the paired bootstrap needs at least one case")
    deltas = [int(a) - int(b) for a, b in pairs]
    n = len(deltas)
    # Not cryptographic: a seeded generator makes the published interval reproducible.
    rng = random.Random(seed)  # noqa: S311
    estimates = [sum(rng.choices(deltas, k=n)) / n for _ in range(resamples)]
    tail = (1 - confidence) / 2
    return PairedDifference(
        cases=n,
        difference=sum(deltas) / n,
        low=percentile(estimates, tail),
        high=percentile(estimates, 1 - tail),
        resamples=resamples,
        seed=seed,
    )
