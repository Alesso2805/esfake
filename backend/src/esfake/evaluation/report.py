"""Plain-text report of one evaluation run (EF-08; ADR-0006 B, Report).

It prints case_ids, levels and counts only, never message text.
"""

from esfake.evaluation.gate import GateResult, PairedOutcome
from esfake.evaluation.metrics import LABELS, LEVELS, Metrics, Proportion


def _proportion(p: Proportion) -> str:
    if p.value is None:
        return "n/a (0 cases)"
    return f"{p.value:.1%} [{p.low:.1%}, {p.high:.1%}] ({p.count}/{p.total})"


def _paired(name: str, outcome: PairedOutcome) -> list[str]:
    lines = [
        f"  {name}: {len(outcome.worse)} worse, {len(outcome.better)} better on {outcome.cases} "
        f"cases (p worse = {outcome.p_worse:.4f}, p better = {outcome.p_better:.4f})"
    ]
    for kind, cases in (("worse", outcome.worse), ("better", outcome.better)):
        lines += [f"    {kind}: {c.case_id} {c.baseline} -> {c.current}" for c in cases]
    return lines


def format_report(mode: str, manifest_hash: str, metrics: Metrics, gate: GateResult) -> str:
    lines = [
        f"Evaluation on `eval` ({mode}), manifest {manifest_hash[:12]}, {metrics.cases} cases",
        "",
        f"  {'level':<12}" + "".join(f"{label:>8}" for label in LABELS),
    ]
    lines += [
        f"  {level:<12}" + "".join(f"{metrics.matrix[level][label]:>8}" for label in LABELS)
        for level in LEVELS
    ]
    lines += [
        "",
        f"Recall:          {_proportion(metrics.recall)}",
        f"Strict recall:   {_proportion(metrics.strict_recall)}",
        f"False positives: {_proportion(metrics.false_positive_rate)}",
        f"Model used:      {_proportion(metrics.llm_used)}",
        "Routes:          " + ", ".join(f"{r} {n}" for r, n in metrics.routes.items()),
        "By modality:     "
        + ", ".join(
            f"{code} {c.detected}/{c.cases} (strict {c.likely_scam})"
            for code, c in metrics.by_modality.items()
        ),
        "By subcategory:  "
        + ", ".join(
            f"{code} {c.false_positives}/{c.cases} FP" for code, c in metrics.by_subcategory.items()
        ),
        f"Cost:            US${metrics.cost_usd_total} total, mean US${metrics.cost_usd_mean}",
        f"Latency:         p50 {metrics.latency_ms_p50} ms, p95 {metrics.latency_ms_p95} ms",
        "",
        "Hard negatives:  "
        + (
            ", ".join(
                f"{code} {c.false_positives}/{c.cases} FP"
                for code, c in gate.hard_negative_false_positives.items()
            )
            or "none in this split"
        ),
    ]
    if gate.baseline_version is not None:
        lines.append(f"Compared with {gate.baseline_version} on {gate.compared_cases} cases:")
        if gate.recall is not None:
            lines += _paired("recall", gate.recall)
        if gate.false_positives is not None:
            lines += _paired("false positives", gate.false_positives)
    lines += [f"WARNING: {warning}" for warning in gate.warnings]
    lines += [f"FAILED: {failure}" for failure in gate.failures]
    lines.append("Gate passed." if gate.passed else "Gate failed.")
    return "\n".join(lines)
