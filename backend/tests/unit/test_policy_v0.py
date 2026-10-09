import pytest

from esfake.pipeline.decision.policy_v0 import decide
from esfake.pipeline.verdict import Layer, Signal
from esfake.shared.thresholds import PolicyV0Thresholds, load_thresholds
from tests.paths import CONFIG_DIR

POLICY = PolicyV0Thresholds(suspicious_at=1.0, likely_scam_at=3.0)


def signal(weight: float, modality: str | None = None, layer: Layer = "rules") -> Signal:
    return Signal(layer=layer, code=f"code_{weight}", weight=weight, modality=modality)


def test_the_configured_policy_is_the_one_confirmed_for_version_zero() -> None:
    assert load_thresholds(CONFIG_DIR).policy_v0 == POLICY


@pytest.mark.parametrize(
    ("signals", "level", "route"),
    [
        ([], "no_signals", "no_route"),
        ([signal(0.5)], "no_signals", "no_route"),
        ([signal(0.5), signal(0.5)], "suspicious", "early_exit"),
        ([signal(2.0, "fake_prize"), signal(1.0)], "likely_scam", "early_exit"),
    ],
)
def test_levels_follow_the_sum_of_weights(signals: list[Signal], level: str, route: str) -> None:
    verdict = decide(signals, POLICY)

    assert (verdict.level, verdict.route) == (level, route)
    assert verdict.score == sum(s.weight for s in signals)


def test_likely_scam_needs_a_modality() -> None:
    verdict = decide([signal(3.5)], POLICY)

    assert verdict.level == "suspicious"
    assert verdict.modality is None


def test_the_modality_comes_from_the_heaviest_signal_that_has_one() -> None:
    verdict = decide([signal(1.0, "fake_prize"), signal(2.5, "family_emergency")], POLICY)

    assert (verdict.level, verdict.modality) == ("likely_scam", "family_emergency")


@pytest.mark.parametrize(
    "signals",
    [
        [signal(0.1, layer="injection")],
        [signal(1.0), signal(-2.0)],
    ],
)
def test_injection_or_a_strong_signal_keeps_at_least_suspicious(signals: list[Signal]) -> None:
    # CLAUDE.md rule 3: negative weights cannot pull these below `suspicious`.
    assert decide(signals, POLICY).level == "suspicious"


def test_the_policy_rejects_unordered_thresholds() -> None:
    with pytest.raises(ValueError, match="above suspicious_at"):
        PolicyV0Thresholds(suspicious_at=3.0, likely_scam_at=1.0)
