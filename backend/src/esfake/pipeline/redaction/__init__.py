"""Stage 1b: redaction (ADR-0004 §1). The only place that turns RawText into RedactedText."""

from esfake.pipeline.redaction.deterministic import redact_deterministic
from esfake.pipeline.redaction.names import NameFinder, Span
from esfake.pipeline.text import RawText, RedactedText

# Part of every manifest; bump it whenever patterns, models or the exemption list change.
REDACTOR_VERSION = "1"
NAME_PLACEHOLDER = "[NAME]"


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class Redactor:
    """Deterministic patterns first, then person names when a NameFinder is given."""

    def __init__(self, names: NameFinder | None = None) -> None:
        self._names = names

    def redact(self, raw: RawText) -> RedactedText:
        """Redact normalised text (run `normalize` first)."""
        text, counts = redact_deterministic(raw.reveal())
        if self._names is not None:
            for start, end in reversed(_merge(self._names.find(text))):
                text = text[:start] + NAME_PLACEHOLDER + text[end:]
                counts["name"] += 1
        return RedactedText(text, dict(counts))
