"""Stage 1b: redaction (ADR-0004 §1). The only place that turns RawText into RedactedText."""

from pathlib import Path

from esfake.pipeline.redaction.deterministic import redact_deterministic
from esfake.pipeline.redaction.names import NameFinder, SpacyNameFinder, Span
from esfake.pipeline.text import RawText, RedactedText
from esfake.pipeline.urls.config import load_url_data
from esfake.pipeline.urls.suffixes import PublicSuffixList
from esfake.shared.brands import exempt_terms
from esfake.shared.config import ModelSettings
from esfake.shared.models_config import load_models_config

# Part of every manifest; bump it whenever patterns, models or the exemption list change.
REDACTOR_VERSION = "3"
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
    """Deterministic patterns first, then person names when a NameFinder is given.

    URLs are found with the Public Suffix List; without one, the vendored list of the configured
    config directory applies, so no redactor can skip bare-host URLs.
    """

    def __init__(
        self, names: NameFinder | None = None, suffixes: PublicSuffixList | None = None
    ) -> None:
        self._names = names
        self._suffixes = suffixes or load_url_data(ModelSettings().config_dir).suffixes

    @property
    def suffixes(self) -> PublicSuffixList:
        return self._suffixes

    def redact(self, raw: RawText) -> RedactedText:
        """Redact normalised text (run `normalize` first)."""
        text, counts = redact_deterministic(raw.reveal(), self._suffixes)
        if self._names is not None:
            for start, end in reversed(_merge(self._names.find(text))):
                text = text[:start] + NAME_PLACEHOLDER + text[end:]
                counts["name"] += 1
        return RedactedText(text, dict(counts))


def build_redactor(config_dir: Path) -> Redactor:
    """The production redactor: deterministic patterns plus the spaCy model of models.yaml."""
    model = load_models_config(config_dir).spacy.name
    if model is None:
        raise ValueError("config/models.yaml names no spaCy model")
    return Redactor(
        SpacyNameFinder(model, exempt_terms(config_dir)),
        load_url_data(config_dir).suffixes,
    )
