"""URLs in redacted text, with their offsets (ADR-0005; CLAUDE.md rule 10).

Scams often drop the scheme ("bcp-validacion.com/pago"), so bare hosts count too, but only when
their top-level label is in the Public Suffix List: "S/.500" or "1.000" are not URLs.
The host comes from `urllib.parse`, which also sees through "https://www.bcp.com.pe@evil.com".
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

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


def find_urls(text: str, suffixes: PublicSuffixList) -> list[FoundUrl]:
    found = []
    for match in _URL.finditer(text):
        url = _trim(match.group())
        with_scheme = url if "://" in url else f"http://{url}"
        try:
            hostname = urlsplit(with_scheme).hostname
        except ValueError:
            continue
        labels = (hostname or "").rstrip(".").split(".")
        if len(labels) < 2 or not all(_LABEL.fullmatch(label) for label in labels):
            continue
        host = ".".join(_decode(label) for label in labels).lower()
        if not suffixes.knows_top_level(host.rsplit(".", 1)[-1]):
            continue
        start = match.start()
        found.append(
            FoundUrl(
                start=start,
                end=start + len(url),
                url=url,
                host=host,
                punycode=any(label.startswith("xn--") for label in labels),
            )
        )
    return found
