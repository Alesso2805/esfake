"""Per-URL findings: what the `urls` table stores and the URL layer turns into signals.

A domain that an official brand owns raises nothing. Any other domain is checked for a brand name
in its labels ("bcp-validacion.com"), for an owner label that imitates an official one
("lnterbank.pe"), and for characters outside ASCII or from several scripts in one label.
"""

import re
import unicodedata
from dataclasses import dataclass

from esfake.pipeline.text import RedactedText
from esfake.pipeline.urls.config import UrlData
from esfake.pipeline.urls.confusables import shape
from esfake.pipeline.urls.extract import find_urls
from esfake.pipeline.urls.lookalike import Lookalike, closest_official


@dataclass(frozen=True)
class UrlFinding:
    start: int
    end: int
    url: str  # already redacted: the redactor replaced query strings and identifiers
    host: str
    registered_domain: str | None
    is_shortener: bool
    punycode: bool
    is_idn: bool  # some label has characters outside ASCII
    mixed_script: bool  # some label mixes scripts, such as Latin and Cyrillic
    brand_token: str | None = None  # the brand named in a domain it does not own
    lookalike_of: str | None = None  # the official domain imitated
    lookalike_score: float | None = None


def _scripts(label: str) -> set[str]:
    """Scripts of the letters in a label, from their Unicode names ("LATIN", "CYRILLIC")."""
    return {unicodedata.name(char, "?").split()[0] for char in label if char.isalpha()}


def _named_brand(host: str, suffix: str, data: UrlData) -> str | None:
    raw_labels = host[: -len(suffix) - 1].split(".")
    labels = [shape(label, data.confusables) for label in raw_labels]
    # Hyphens and digits separate parts: "mibcp24" holds the part "mibcp".
    parts = [
        shape(part, data.confusables)
        for label in raw_labels
        for part in re.split(r"[-0-9]+", label)
        if part
    ]
    return next((brand.name for brand in data.brands if brand.named_in(parts, labels)), None)


def _imitated(registered: str, suffix: str, data: UrlData) -> Lookalike | None:
    closest = closest_official(registered[: -len(suffix) - 1], data.brands, data.confusables)
    if closest is None or closest.similarity < data.lookalike_min_similarity:
        return None
    return closest


def analyze_urls(message: RedactedText, data: UrlData) -> list[UrlFinding]:
    findings = []
    for found in find_urls(message.value, data.suffixes):
        registered = data.suffixes.registered_domain(found.host)
        brand_token, lookalike = None, None
        if registered is not None and not any(brand.owns(found.host) for brand in data.brands):
            suffix = data.suffixes.public_suffix(registered)
            brand_token = _named_brand(found.host, suffix, data)
            lookalike = _imitated(registered, suffix, data)
        findings.append(
            UrlFinding(
                start=found.start,
                end=found.end,
                url=found.url,
                host=found.host,
                registered_domain=registered,
                is_shortener=registered in data.config.shorteners,
                punycode=found.punycode,
                is_idn=not found.host.isascii(),
                mixed_script=any(len(_scripts(label)) > 1 for label in found.host.split(".")),
                brand_token=brand_token,
                lookalike_of=lookalike.domain if lookalike else None,
                lookalike_score=lookalike.similarity if lookalike else None,
            )
        )
    return findings
