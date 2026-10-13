"""Per-URL findings: what the `urls` table stores and the URL layer turns into signals."""

from dataclasses import dataclass

from esfake.pipeline.text import RedactedText
from esfake.pipeline.urls.config import UrlData
from esfake.pipeline.urls.extract import find_urls


@dataclass(frozen=True)
class UrlFinding:
    start: int
    end: int
    url: str  # already redacted: the redactor replaced query strings and identifiers
    host: str
    registered_domain: str | None
    is_shortener: bool
    punycode: bool


def analyze_urls(message: RedactedText, data: UrlData) -> list[UrlFinding]:
    findings = []
    for found in find_urls(message.value, data.suffixes):
        registered = data.suffixes.registered_domain(found.host)
        findings.append(
            UrlFinding(
                start=found.start,
                end=found.end,
                url=found.url,
                host=found.host,
                registered_domain=registered,
                is_shortener=registered in data.config.shorteners,
                punycode=found.punycode,
            )
        )
    return findings
