from esfake.evaluation.gate import Baseline, run_gate
from esfake.evaluation.metrics import CasePrediction, LegitCounts
from esfake.pipeline.verdict import Level
from esfake.shared.thresholds import EvaluationThresholds

FLOORS_OFF = EvaluationThresholds(
    absolute_floors_enabled=False, recall_floor=0.85, false_positive_ceiling=0.08
)
FLOORS_ON = FLOORS_OFF.model_copy(update={"absolute_floors_enabled": True})
HARD = frozenset({"bank_notification", "otp_code"})


def scams(prefix: str, n: int, level: Level, *, live: bool = False) -> list[CasePrediction]:
    return [
        CasePrediction(
            case_id=f"{prefix}{i}",
            label="scam",
            modality="fake_prize",
            level=level,
            route="early_exit",
            llm_used=live,
            live_call=live,
        )
        for i in range(n)
    ]


def legits(prefix: str, n: int, level: Level, subcategory: str = "easy") -> list[CasePrediction]:
    return [
        CasePrediction(
            case_id=f"{prefix}{i}",
            label="legit",
            subcategory=subcategory,
            level=level,
            route="no_route",
        )
        for i in range(n)
    ]


def baseline(levels: dict[str, Level]) -> Baseline:
    return Baseline(version="v0", levels=levels)


def same_levels(predictions: list[CasePrediction]) -> dict[str, Level]:
    return {p.case_id: p.level for p in predictions}


def test_before_version_zero_the_gate_passes_with_a_warning() -> None:
    result = run_gate(scams("s", 3, "no_signals"), None, FLOORS_OFF, HARD)

    assert result.passed
    assert result.baseline_version is None
    assert "No published version yet" in result.warnings[0]


def test_five_scams_lost_without_gains_fail_the_gate() -> None:
    current = scams("s", 5, "no_signals") + scams("k", 20, "likely_scam")
    result = run_gate(
        current, baseline(same_levels(scams("s", 25, "likely_scam"))), FLOORS_OFF, HARD
    )

    assert not result.passed
    assert result.recall is not None
    assert [d.case_id for d in result.recall.worse] == [f"s{i}" for i in range(5)]
    assert result.recall.p_worse == 1 / 32
    assert "recall regressed against v0" in result.failures[0]


def test_four_scams_lost_are_not_a_significant_regression() -> None:
    current = scams("s", 4, "no_signals")
    result = run_gate(current, baseline(same_levels(scams("s", 4, "suspicious"))), FLOORS_OFF, HARD)

    assert result.passed
    assert result.recall is not None
    assert result.recall.p_worse == 1 / 16


def test_false_positives_rising_without_a_recall_gain_fail_the_gate() -> None:
    current = legits("l", 5, "suspicious", "bank_notification") + legits("e", 5, "no_signals")
    previous = legits("l", 5, "no_signals") + legits("e", 5, "no_signals")

    result = run_gate(current, baseline(same_levels(previous)), FLOORS_OFF, HARD)

    assert not result.passed
    assert "false positives rose" in result.failures[0]
    assert result.hard_negative_false_positives == {
        "bank_notification": LegitCounts(cases=5, false_positives=5)
    }


def test_false_positives_may_rise_when_they_buy_a_significant_recall_gain() -> None:
    # Version 0 says no_signals to everything; the first rules (EF-11) flag more of both labels.
    current = scams("s", 6, "likely_scam") + legits("l", 5, "suspicious")
    previous = scams("s", 6, "no_signals") + legits("l", 5, "no_signals")

    result = run_gate(current, baseline(same_levels(previous)), FLOORS_OFF, HARD)

    assert result.passed
    assert result.recall is not None
    assert result.recall.p_better < 0.05
    assert result.false_positives is not None
    assert len(result.false_positives.worse) == 5


def test_only_cases_in_both_versions_are_compared() -> None:
    current = scams("s", 2, "likely_scam") + scams("new", 10, "no_signals")

    result = run_gate(
        current, baseline(same_levels(scams("s", 2, "likely_scam"))), FLOORS_OFF, HARD
    )

    assert result.passed
    assert result.compared_cases == 2


def test_responses_recorded_live_are_left_out_of_the_comparison() -> None:
    current = scams("s", 6, "no_signals", live=True)

    result = run_gate(
        current, baseline(same_levels(scams("s", 6, "likely_scam"))), FLOORS_OFF, HARD
    )

    assert result.passed
    assert (result.compared_cases, result.left_out_live) == (0, 6)
    assert any("left out" in warning for warning in result.warnings)


def test_absolute_floors_apply_only_when_enabled() -> None:
    # Recall 80 % and false positives 10 %: both outside the floors, with no regression.
    current = (
        scams("s", 8, "likely_scam")
        + scams("m", 2, "no_signals")
        + legits("l", 1, "suspicious")
        + legits("e", 9, "no_signals")
    )
    previous = baseline(same_levels(current))

    assert run_gate(current, previous, FLOORS_OFF, HARD).passed
    failures = run_gate(current, previous, FLOORS_ON, HARD).failures
    assert failures == (
        "recall 80.0% is below the floor of 85%",
        "false positives 10.0% are above the ceiling of 8%",
    )
