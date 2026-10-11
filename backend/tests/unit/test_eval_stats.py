from typing import get_args

import pytest

from esfake.evaluation.stats import (
    mcnemar_one_sided,
    paired_bootstrap,
    percentile,
    wilson_interval,
)
from esfake.pipeline.verdict import Level, Route
from esfake.shared.db.base import LEVELS, ROUTES


def test_verdict_literals_match_the_database_checks() -> None:
    assert get_args(Level.__value__) == LEVELS
    assert get_args(Route.__value__) == ROUTES


def test_wilson_interval_matches_the_published_redaction_floor() -> None:
    low, high = wilson_interval(115, 120)  # ADR-0004 amendment 1

    assert round(low, 3) == 0.906
    assert high < 1
    assert wilson_interval(0, 0) == (0.0, 1.0)


@pytest.mark.parametrize(
    ("worse", "better", "p"),
    [
        (0, 0, 1.0),
        (4, 0, 1 / 16),
        (5, 0, 1 / 32),
        (6, 2, 37 / 256),
        (0, 5, 1.0),
    ],
)
def test_exact_mcnemar_is_the_upper_binomial_tail(worse: int, better: int, p: float) -> None:
    assert mcnemar_one_sided(worse, better) == pytest.approx(p)


def test_percentile_interpolates_between_ranks() -> None:
    assert percentile([4, 1, 3, 2], 0.5) == 2.5
    assert percentile([4, 1, 3, 2], 0) == 1
    assert percentile([4, 1, 3, 2], 1) == 4
    with pytest.raises(ValueError, match="empty"):
        percentile([], 0.5)


def test_paired_bootstrap_is_reproducible_and_brackets_the_difference() -> None:
    # 40 scams: both systems catch 34, the pipeline alone 2, the baseline alone 4.
    pairs = [(True, True)] * 34 + [(True, False)] * 2 + [(False, True)] * 4

    first = paired_bootstrap(pairs, resamples=2_000)
    second = paired_bootstrap(pairs, resamples=2_000)

    assert first == second
    assert first.difference == pytest.approx(-0.05)
    assert first.low < first.difference < first.high
    assert first.low > -0.2
    assert first.high < 0.1
    assert (first.cases, first.resamples) == (40, 2_000)


def test_paired_bootstrap_without_discordant_cases_has_no_spread() -> None:
    result = paired_bootstrap([(True, True), (False, False)], resamples=100)

    assert (result.difference, result.low, result.high) == (0, 0, 0)
    with pytest.raises(ValueError, match="at least one case"):
        paired_bootstrap([])
