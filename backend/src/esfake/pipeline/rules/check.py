"""Manual check of the rule layer: what a message triggers, for reviewing config/rules.yaml."""

from collections.abc import Sequence

from esfake.pipeline.decision.policy_v0 import decide
from esfake.pipeline.rules.detector import RuleDetector
from esfake.pipeline.text import RedactedText
from esfake.shared.thresholds import PolicyV0Thresholds

_MAX_SNIPPET = 60


def check_message(message: RedactedText, detector: RuleDetector, policy: PolicyV0Thresholds) -> str:
    """Level, score and every signal with the text that triggered it (local terminal only)."""
    signals = detector.detect(message)
    verdict = decide(signals, policy)
    head = f"{verdict.level} (score {verdict.score:.1f}, modality {verdict.modality or '-'})"
    lines = [head]
    for signal in sorted(signals, key=lambda s: -s.weight):
        lines.append(
            f"  {signal.layer:<9} {signal.code:<26} {signal.weight:>4.1f}  "
            f"{_snippets(message.value, signal.spans)}"
        )
    if not signals:
        lines.append("  (no rule matched)")
    return "\n".join(lines)


def _snippets(text: str, spans: Sequence[tuple[int, int]]) -> str:
    parts = []
    for start, end in spans:
        piece = " ".join(text[start:end].split())
        if len(piece) > _MAX_SNIPPET:
            piece = piece[: _MAX_SNIPPET - 1] + "..."
        parts.append(f'"{piece}"')
    return " | ".join(parts)
