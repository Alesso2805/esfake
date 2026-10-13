"""Detector for the URL layer (EF-12): one `Signal` per kind of finding in a message.

A signal carries the spans of every URL that raised it, so two fake bank links weigh as one
brand-name signal, as a rule that matches twice does. Weights and the modality of each brand come
from config/urls.yaml.
"""

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from esfake.pipeline.text import RedactedText
from esfake.pipeline.urls.analysis import UrlFinding, analyze_urls
from esfake.pipeline.urls.config import URL_SIGNAL_CODES, UrlData, UrlSignalCode, load_url_data
from esfake.pipeline.verdict import Signal


def _codes(finding: UrlFinding) -> list[UrlSignalCode]:
    codes: list[UrlSignalCode] = []
    if finding.brand_token is not None:
        codes.append("url_brand_unofficial")
    if finding.lookalike_of is not None:
        codes.append("url_lookalike")
    if finding.mixed_script:
        codes.append("url_mixed_script")
    elif finding.is_idn:
        codes.append("url_idn")
    if finding.is_shortener:
        codes.append("url_shortener")
    return codes


class UrlDetector:
    def __init__(self, data: UrlData) -> None:
        self._data = data

    @classmethod
    def from_config(cls, config_dir: Path) -> UrlDetector:
        return cls(load_url_data(config_dir))

    def _brand(self, code: UrlSignalCode, finding: UrlFinding) -> str | None:
        if code == "url_brand_unofficial":
            return finding.brand_token
        if code == "url_lookalike":
            return next(
                (b.name for b in self._data.brands if finding.lookalike_of in b.domains), None
            )
        return None

    def detect(self, message: RedactedText) -> Sequence[Signal]:
        raised: dict[UrlSignalCode, list[UrlFinding]] = defaultdict(list)
        for finding in analyze_urls(message, self._data):
            for code in _codes(finding):
                raised[code].append(finding)
        signals = []
        for code in URL_SIGNAL_CODES:
            findings = raised.get(code)
            if not findings:
                continue
            brand = self._brand(code, findings[0])
            signals.append(
                Signal(
                    layer="urls",
                    code=code,
                    weight=self._data.config.signals[code],
                    modality=self._data.config.brand_modalities.get(brand) if brand else None,
                    spans=tuple((f.start, f.end) for f in findings),
                )
            )
        return signals
