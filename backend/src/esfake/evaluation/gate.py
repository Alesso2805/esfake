"""Per-PR regression gate on `eval` (ADR-0006 B; CLAUDE.md rule 11).

The current predictions are paired by case_id with the ones stored for the latest published
version, and only the cases present in both are compared: old code never runs again. Responses
recorded live during the run are left out of the comparison.
"""

from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict

from esfake.evaluation.metrics import CasePrediction, LegitCounts, Metrics, compute_metrics
from esfake.evaluation.stats import mcnemar_one_sided
from esfake.pipeline.verdict import Level
from esfake.shared.thresholds import EvaluationThresholds

ALPHA = 0.05


class Baseline(BaseModel):
    """Per-case levels of the latest published version (`docs/evals/<version>.json`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    levels: dict[str, Level]


class Discordant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    baseline: Level
    current: Level


class PairedOutcome(BaseModel):
    """One outcome compared case by case.

    `worse` holds the cases the current version gets wrong and the baseline got right; `better`
    the reverse. Each p-value is the exact one-sided McNemar test in that direction.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    cases: int
    worse: tuple[Discordant, ...]
    better: tuple[Discordant, ...]
    p_worse: float
    p_better: float


class GateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    baseline_version: str | None
    compared_cases: int
    left_out_live: int
    recall: PairedOutcome | None
    false_positives: PairedOutcome | None
    hard_negative_false_positives: dict[str, LegitCounts]
    failures: tuple[str, ...]
    warnings: tuple[str, ...]


def _paired(
    cases: Sequence[CasePrediction], baseline: dict[str, Level], right: Callable[[Level], bool]
) -> PairedOutcome:
    def discordant(case: CasePrediction) -> Discordant:
        return Discordant(case_id=case.case_id, baseline=baseline[case.case_id], current=case.level)

    worse = tuple(discordant(c) for c in cases if right(baseline[c.case_id]) and not right(c.level))
    better = tuple(
        discordant(c) for c in cases if right(c.level) and not right(baseline[c.case_id])
    )
    return PairedOutcome(
        cases=len(cases),
        worse=worse,
        better=better,
        p_worse=mcnemar_one_sided(len(worse), len(better)),
        p_better=mcnemar_one_sided(len(better), len(worse)),
    )


def _detected(level: Level) -> bool:
    return level != "no_signals"


def _no_false_positive(level: Level) -> bool:
    return level == "no_signals"


def _floor_failures(metrics: Metrics, floors: EvaluationThresholds) -> list[str]:
    recall, false_positives = metrics.recall.value, metrics.false_positive_rate.value
    failures = []
    if recall is None or recall < floors.recall_floor:
        failures.append(
            f"recall {_percent(recall)} is below the floor of {floors.recall_floor:.0%}"
        )
    if false_positives is None or false_positives > floors.false_positive_ceiling:
        failures.append(
            f"false positives {_percent(false_positives)} are above the ceiling of "
            f"{floors.false_positive_ceiling:.0%}"
        )
    return failures


def _percent(value: float | None) -> str:
    return "n/a (no cases)" if value is None else f"{value:.1%}"


def run_gate(
    predictions: Sequence[CasePrediction],
    baseline: Baseline | None,
    floors: EvaluationThresholds,
    hard_negatives: frozenset[str],
) -> GateResult:
    metrics = compute_metrics(predictions)
    hard = {code: c for code, c in metrics.by_subcategory.items() if code in hard_negatives}
    failures = _floor_failures(metrics, floors) if floors.absolute_floors_enabled else []
    warnings: list[str] = []
    if baseline is None:
        warnings.append("No published version yet: the gate passes without a comparison.")
        return GateResult(
            passed=not failures,
            baseline_version=None,
            compared_cases=0,
            left_out_live=0,
            recall=None,
            false_positives=None,
            hard_negative_false_positives=hard,
            failures=tuple(failures),
            warnings=tuple(warnings),
        )

    common = [p for p in predictions if p.case_id in baseline.levels]
    compared = [p for p in common if not p.live_call]
    left_out = len(common) - len(compared)
    if left_out:
        warnings.append(f"{left_out} responses recorded live in this run were left out.")
    if not compared:
        warnings.append(f"No case in common with {baseline.version}: nothing was compared.")

    recall = _paired([p for p in compared if p.label == "scam"], baseline.levels, _detected)
    false_positives = _paired(
        [p for p in compared if p.label == "legit"], baseline.levels, _no_false_positive
    )
    if recall.p_worse < ALPHA:
        failures.append(
            f"recall regressed against {baseline.version}: {len(recall.worse)} scams missed that "
            f"it caught, {len(recall.better)} caught that it missed (p = {recall.p_worse:.4f})"
        )
    if false_positives.p_worse < ALPHA and recall.p_better >= ALPHA:
        failures.append(
            f"false positives rose against {baseline.version} without a significant recall gain: "
            f"{len(false_positives.worse)} new, {len(false_positives.better)} fixed "
            f"(p = {false_positives.p_worse:.4f}; recall gain p = {recall.p_better:.4f})"
        )
    return GateResult(
        passed=not failures,
        baseline_version=baseline.version,
        compared_cases=len(compared),
        left_out_live=left_out,
        recall=recall,
        false_positives=false_positives,
        hard_negative_false_positives=hard,
        failures=tuple(failures),
        warnings=tuple(warnings),
    )
