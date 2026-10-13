"""URLs in text, with their offsets (ADR-0005; CLAUDE.md rule 10).

`find_url_spans` is the one definition of a URL in a message, shared by redaction (ADR-0004) and
URL analysis (docs/ARCHITECTURE_RULES.md, rule 3):
- anything written with a scheme ("https://..."), whatever its host, so a link to a bare IP
  still loses its query when redacted;
- a bare host ("bcp-validacion.com/pago"), since scams often drop the scheme, but only when the
  Public Suffix List knows its top-level label ("S/.500" or "1.000" are not URLs) and it is not
  the local part of an address ("maria.pe@gmail.com" is an address, left to the e-mail rule).

`find_urls` keeps the spans whose host has a known suffix and reads that host after the last "@",
so "https://www.bcp.com.pe@evil.com" points to evil.com. The host is parsed by hand: Python's
urlsplit refuses a redacted "[USERINFO]@evil.com".
"""

import re
from dataclasses import dataclass

from esfake.pipeline.urls.suffixes import PublicSuffixList

_URL = re.compile(
    r"(?<![\w@.-])"  # not inside a word, an address or a longer host
    r"(?:https?://[^\s<>\"']+"  # with a scheme: up to whitespace
    r"|(?:[\w-]+\.)+[^\W\d_][\w-]*"  # a bare host: its last label starts with a letter
    r"(?::\d{1,5})?(?:[/?#][^\s<>\"']*)?)",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?¡¿)]}…»\"'"
_OPENERS = {")": "(", "]": "[", "}": "{"}
_LABEL = re.compile(r"[\w-]{1,63}")


@dataclass(frozen=True)
class UrlSpan:
    start: int
    end: int
    url: str


@dataclass(frozen=True)
class FoundUrl:
    start: int
    end: int
    url: str
    host: str  # lower case, punycode labels decoded
    punycode: bool  # some label was written as xn--


def _decode(label: str) -> str:
    if not label.startswith("xn--"):
        return label
    try:
        return label.encode("ascii").decode("idna")
    except UnicodeError:
        return label  # malformed punycode stays as written


def _trim(url: str) -> str:
    """Drop sentence punctuation after a URL, but keep a closing bracket it opened: [QUERY]."""
    while url and url[-1] in _TRAILING:
        opener = _OPENERS.get(url[-1])
        if opener is not None and url.count(opener) >= url.count(url[-1]):
            break
        url = url[:-1]
    return url


def _host_labels(url: str) -> list[str] | None:
    """The labels of the host: after the scheme and the last "@", before the port and the path."""
    rest = url.split("://", 1)[1] if "://" in url else url
    netloc = re.split(r"[/?#]", rest, maxsplit=1)[0]
    host = re.sub(r":\d*$", "", netloc.rsplit("@", 1)[-1]).rstrip(".")
    labels = host.split(".")
    if len(labels) < 2 or not all(_LABEL.fullmatch(label) for label in labels):
        return None
    return labels


def _known_suffix(labels: list[str], suffixes: PublicSuffixList) -> bool:
    return suffixes.knows_top_level(_decode(labels[-1]).lower())


def find_url_spans(text: str, suffixes: PublicSuffixList) -> list[UrlSpan]:
    spans = []
    for match in _URL.finditer(text):
        url = _trim(match.group())
        if "://" not in url:
            if text.startswith("@", match.end()):
                continue  # the local part of an e-mail address
            labels = _host_labels(url)
            if labels is None or not _known_suffix(labels, suffixes):
                continue
        spans.append(UrlSpan(match.start(), match.start() + len(url), url))
    return spans


def find_urls(text: str, suffixes: PublicSuffixList) -> list[FoundUrl]:
    found = []
    for span in find_url_spans(text, suffixes):
        labels = _host_labels(span.url)
        if labels is None or not _known_suffix(labels, suffixes):
            continue
        found.append(
            FoundUrl(
                start=span.start,
                end=span.end,
                url=span.url,
                host=".".join(_decode(label) for label in labels).lower(),
                punycode=any(label.lower().startswith("xn--") for label in labels),
            )
        )
    return found
