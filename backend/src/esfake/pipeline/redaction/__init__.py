"""Stage 1b: redaction (ADR-0004 §1). The only place that turns RawText into RedactedText."""

from esfake.pipeline.redaction.deterministic import redact_deterministic
from esfake.pipeline.text import RawText, RedactedText

# Part of every manifest; bump it whenever patterns, models or the exemption list change.
REDACTOR_VERSION = "1"


class Redactor:
    def redact(self, raw: RawText) -> RedactedText:
        """Redact normalised text (run `normalize` first)."""
        text, counts = redact_deterministic(raw.reveal())
        return RedactedText(text, dict(counts))
