"""Policy v0 (EF-08): a threshold on the sum of signal weights, until EF-15 replaces it.

Already holds the floors of CLAUDE.md rule 3 that need no calibration: any injection signal, or
any single signal at or above the `suspicious` threshold, keeps the level at `suspicious` or
above, even when other signals carry negative weights. `likely_scam` needs a modality (a CHECK
on `verdicts`), taken from the heaviest signal that has one.
"""

from collections.abc import Sequence

from esfake.pipeline.verdict import Level, Signal, Verdict
from esfake.shared.thresholds import PolicyV0Thresholds


def decide(signals: Sequence[Signal], thresholds: PolicyV0Thresholds) -> Verdict:
    score = sum(signal.weight for signal in signals)
    with_modality = [signal for signal in signals if signal.modality is not None]
    modality = max(with_modality, key=lambda s: s.weight).modality if with_modality else None
    floor = any(
        signal.layer == "injection" or signal.weight >= thresholds.suspicious_at
        for signal in signals
    )
    level: Level
    if score >= thresholds.likely_scam_at and modality is not None:
        level = "likely_scam"
    elif score >= thresholds.suspicious_at or floor:
        level = "suspicious"
    else:
        level = "no_signals"
    return Verdict(
        level=level,
        route="no_route" if level == "no_signals" else "early_exit",
        score=score,
        modality=None if level == "no_signals" else modality,
        signals=tuple(signals),
    )
