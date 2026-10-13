"""How closely a domain imitates an official one (ADR-0005 §2): UTS #39 skeleton and edit distance.

Owner labels are compared ("interbank" in interbank.pe), skeleton against skeleton, so a
swapped letter ("lnterbank"), a confusable character (a Cyrillic i, U+0456, for the Latin one)
and the same name under another suffix ("interbank.com") all come out close to 1.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from esfake.pipeline.urls.confusables import shape
from esfake.pipeline.urls.official import OfficialBrand


@dataclass(frozen=True)
class Lookalike:
    brand: str
    domain: str  # the official domain imitated
    similarity: float  # 1 - normalised edit distance between skeletons


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b))
            )
        previous = current
    return previous[-1]


def similarity(a: str, b: str) -> float:
    longest = max(len(a), len(b))
    return 1.0 if longest == 0 else 1 - edit_distance(a, b) / longest


def closest_official(
    label: str, brands: Sequence[OfficialBrand], confusables: Mapping[str, str]
) -> Lookalike | None:
    """The official domain whose owner label looks most like `label`."""
    target = shape(label, confusables)
    best: Lookalike | None = None
    for brand in brands:
        for domain, official in zip(brand.domains, brand.owner_labels, strict=True):
            if official is None:
                continue
            score = similarity(target, shape(official, confusables))
            if best is None or score > best.similarity:
                best = Lookalike(brand.name, domain, score)
    return best
