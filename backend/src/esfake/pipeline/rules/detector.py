"""Detector for the rules and injection layers: one `Signal` per rule that matches."""

from collections.abc import Sequence
from pathlib import Path

from esfake.pipeline.rules.catalog import RuleCatalog, load_rules
from esfake.pipeline.text import RedactedText
from esfake.pipeline.verdict import Signal


class RuleDetector:
    def __init__(self, catalog: RuleCatalog) -> None:
        self._catalog = catalog

    @classmethod
    def from_config(cls, config_dir: Path) -> RuleDetector:
        return cls(load_rules(config_dir))

    def detect(self, message: RedactedText) -> Sequence[Signal]:
        signals: list[Signal] = []
        for rule in self._catalog.rules:
            spans = rule.spans(message.value)
            if spans:
                signals.append(
                    Signal(
                        layer=rule.layer,
                        code=rule.code,
                        weight=rule.weight,
                        modality=rule.modality,
                        spans=spans,
                    )
                )
        return signals
