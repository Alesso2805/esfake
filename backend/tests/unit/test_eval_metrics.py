from decimal import Decimal

import pytest

from esfake.evaluation.metrics import CasePrediction, LegitCounts, ScamCounts, compute_metrics
from esfake.pipeline.verdict import Level, Route


def scam(
    case_id: str, level: Level, modality: str = "family_emergency", route: Route = "early_exit"
) -> CasePrediction:
    return CasePrediction(
        case_id=case_id, label="scam", modality=modality, level=level, route=route
    )


def legit(case_id: str, level: Level, subcategory: str = "easy") -> CasePrediction:
    return CasePrediction(
        case_id=case_id, label="legit", subcategory=subcategory, level=level, route="no_route"
    )


PREDICTIONS = [
    scam("s1", "likely_scam"),
    scam("s2", "likely_scam"),
    scam("s3", "likely_scam", "fake_prize"),
    scam("s4", "suspicious", "fake_prize", route="gray_zone").model_copy(
        update={"llm_used": True, "cost_usd": Decimal("0.002"), "latency_ms": 900}
    ),
    scam("s5", "no_signals", "fake_prize"),
    legit("l1", "suspicious", "bank_notification"),
    legit("l2", "no_signals", "bank_notification"),
    legit("l3", "no_signals"),
    legit("l4", "no_signals"),
]


def test_the_matrix_crosses_three_levels_with_two_labels() -> None:
    metrics = compute_metrics(PREDICTIONS)

    assert metrics.matrix == {
        "likely_scam": {"scam": 3, "legit": 0},
        "suspicious": {"scam": 1, "legit": 1},
        "no_signals": {"scam": 1, "legit": 3},
    }
    assert metrics.cases == 9


def test_recall_strict_recall_and_false_positives_carry_wilson_intervals() -> None:
    metrics = compute_metrics(PREDICTIONS)

    assert (metrics.recall.count, metrics.recall.total) == (4, 5)
    assert metrics.recall.value == pytest.approx(0.8)
    assert metrics.recall.low < 0.8 < metrics.recall.high
    assert metrics.strict_recall.value == pytest.approx(0.6)
    assert (metrics.false_positive_rate.count, metrics.false_positive_rate.total) == (1, 4)


def test_counts_by_modality_and_subcategory() -> None:
    metrics = compute_metrics(PREDICTIONS)

    assert metrics.by_modality == {
        "family_emergency": ScamCounts(cases=2, detected=2, likely_scam=2),
        "fake_prize": ScamCounts(cases=3, detected=2, likely_scam=1),
    }
    assert metrics.by_subcategory == {
        "bank_notification": LegitCounts(cases=2, false_positives=1),
        "easy": LegitCounts(cases=2, false_positives=0),
    }


def test_routes_model_use_cost_and_latency() -> None:
    metrics = compute_metrics(PREDICTIONS)

    assert metrics.routes == {
        "early_exit": 4,
        "gray_zone": 1,
        "risk_trait": 0,
        "out_of_distribution": 0,
        "no_route": 4,
    }
    assert (metrics.llm_used.count, metrics.llm_used.total) == (1, 9)
    assert metrics.cost_usd_total == Decimal("0.002")
    assert metrics.latency_ms_p95 == pytest.approx(540.0)  # eight at 0 ms and one at 900 ms


def test_an_empty_run_reports_no_values_instead_of_zeros() -> None:
    metrics = compute_metrics([])

    assert metrics.recall.value is None
    assert (metrics.recall.low, metrics.recall.high) == (0.0, 1.0)
    assert metrics.cost_usd_mean is None
    assert metrics.latency_ms_p95 is None


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"label": "scam"}, "needs its modality"),
        ({"label": "legit"}, "needs its subcategory"),
        ({"label": "legit", "subcategory": "easy", "live_call": True}, "live call"),
    ],
)
def test_case_predictions_need_their_expected_fields(fields: dict[str, object], error: str) -> None:
    with pytest.raises(ValueError, match=error):
        CasePrediction.model_validate(
            {"case_id": "c1", "level": "no_signals", "route": "no_route"} | fields
        )
