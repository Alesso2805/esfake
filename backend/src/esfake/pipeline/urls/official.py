"""Official brands seen from URLs: their domains and the names a fake domain borrows (ADR-0005 §2).

Only brands with at least one verified domain take part: without the real domain there is no
telling a real link from a fake one. Brand names to look for in a domain come from the brand's
name and the label of its official domains, never from its aliases: "Falabella" is an alias of
Banco Falabella, and falabella.com is a shop, not a fake bank. An official domain that is a public
suffix (gob.pe for RENIEC) makes every domain under it official for that brand.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass

from esfake.pipeline.urls.confusables import shape
from esfake.pipeline.urls.suffixes import PublicSuffixList
from esfake.shared.brands import BrandCatalog
from esfake.shared.text_folding import fold

MIN_NAME_LENGTH = 3  # "bcp" counts; "bn" (bn.com.pe) and "wa" (wa.me) would match too much
SHORT_NAME_LENGTH = 4  # names this short must start or end a part of the host, not hide in one


@dataclass(frozen=True)
class OfficialBrand:
    name: str
    names: tuple[str, ...]  # letters and digits only, by shape (urls.confusables.shape)
    domains: tuple[str, ...]
    # The owner label of each official domain, in the same order; None for a public suffix.
    owner_labels: tuple[str | None, ...]

    def owns(self, host: str) -> bool:
        return any(host == domain or host.endswith("." + domain) for domain in self.domains)

    def named_in(self, parts: list[str], labels: list[str]) -> bool:
        """Whether a part of the host ("bcp" in "bcp-validacion") or a label carries a name.

        `parts` and `labels` come by shape, so a Cyrillic "c" in "bcp" still reads "bcp".
        """
        for name in self.names:
            if len(name) < SHORT_NAME_LENGTH:
                if any(p.startswith(name) or p.endswith(name) for p in parts):
                    return True
            elif any(name in label for label in labels):
                return True
        return False


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", fold(text))


def official_brands(
    catalog: BrandCatalog, suffixes: PublicSuffixList, confusables: Mapping[str, str]
) -> tuple[OfficialBrand, ...]:
    brands = []
    for brand in catalog.brands:
        if not brand.domains:
            continue
        domains = tuple(domain.lower() for domain in brand.domains)
        owner_labels: list[str | None] = []
        for domain in domains:
            registered = suffixes.registered_domain(domain)
            owner_labels.append(
                None
                if registered is None
                else registered[: -len(suffixes.public_suffix(registered)) - 1]
            )
        compact = {_compact(brand.name), *(_compact(label) for label in owner_labels if label)}
        names = {shape(name, confusables) for name in compact}
        brands.append(
            OfficialBrand(
                name=brand.name,
                names=tuple(sorted(n for n in names if len(n) >= MIN_NAME_LENGTH)),
                domains=domains,
                owner_labels=tuple(owner_labels),
            )
        )
    return tuple(brands)
