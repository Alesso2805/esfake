"""UTS #39 skeletons from the vendored confusables.txt (ADR-0005 §2).

Two strings that look alike share a skeleton: "lnterbank" and "1nterbank", or a Latin "yape"
and one with a Cyrillic a (U+0430). Domains are compared without case, so the skeleton is
lower-cased after the mapping too ("0" maps to a capital "O").
"""

import unicodedata
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from esfake.shared.text_folding import fold


@lru_cache(maxsize=4)
def load_confusables(path: Path) -> Mapping[str, str]:
    mapping: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        source, target, *_ = (field.strip() for field in line.split(";"))
        mapping[chr(int(source, 16))] = "".join(chr(int(point, 16)) for point in target.split())
    if not mapping:
        raise ValueError(f"{path} holds no confusables")
    return mapping


def shape(text: str, confusables: Mapping[str, str]) -> str:
    """What a label looks like: no case, no accents ("yapé" reads "yape"), then its skeleton."""
    return skeleton(fold(text), confusables)


def skeleton(text: str, confusables: Mapping[str, str]) -> str:
    """NFD, each character to its prototype, NFD again (UTS #39 §4), without case."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    mapped = "".join(confusables.get(char, char) for char in decomposed)
    return unicodedata.normalize("NFD", mapped).lower()
