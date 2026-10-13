"""Manual check of the cheap layers: what a message triggers in rules and URLs.

For reviewing config/rules.yaml and config/urls.yaml by hand. Similarity and the judge need
the corpus index and the model, so they stay out of this local aid.
"""

from collections.abc import Sequence
from typing import Protocol

from esfake.pipeline.decision.policy_v0 import decide
from esfake.pipeline.text import RedactedText
from esfake.pipeline.verdict import Signal
from esfake.shared.thresholds import PolicyV0Thresholds

_MAX_SNIPPET = 60


class _Detector(Protocol):
    def detect(self, message: RedactedText) -> Sequence[Signal]: ...


def check_message(
    message: RedactedText, detectors: Sequence[_Detector], policy: PolicyV0Thresholds
) -> str:
    """Level, score and every signal with the text that triggered it (local terminal only)."""
    signals = [signal for detector in detectors for signal in detector.detect(message)]
    verdict = decide(signals, policy)
    head = f"{verdict.level} (score {verdict.score:.1f}, modality {verdict.modality or '-'})"
    lines = [head]
    for signal in sorted(signals, key=lambda s: -s.weight):
        lines.append(
            f"  {signal.layer:<9} {signal.code:<26} {signal.weight:>4.1f}  "
            f"{_snippets(message.value, signal.spans)}"
        )
    if not signals:
        lines.append("  (no rule or URL signal matched)")
    return "\n".join(lines)


def _snippets(text: str, spans: Sequence[tuple[int, int]]) -> str:
    parts = []
    for start, end in spans:
        piece = " ".join(text[start:end].split())
        if len(piece) > _MAX_SNIPPET:
            piece = piece[: _MAX_SNIPPET - 1] + "..."
        parts.append(f'"{piece}"')
    return " | ".join(parts)
