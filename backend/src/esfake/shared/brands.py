"""Official brands from config/official_domains.yaml (ADR-0004 exemptions, ADR-0005)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from esfake.corpus.modalities import load_catalog


class Brand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = Field(min_length=1)
    domains: tuple[str, ...] = ()


class BrandCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    brands: tuple[Brand, ...] = Field(min_length=1)


def load_brands(config_dir: Path) -> BrandCatalog:
    path = config_dir / "official_domains.yaml"
    return BrandCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def exempt_terms(config_dir: Path) -> frozenset[str]:
    """Every brand name that name redaction must keep, from both versioned catalogues."""
    terms = {
        term for brand in load_brands(config_dir).brands for term in (brand.name, *brand.aliases)
    }
    for modality in load_catalog(config_dir / "modalities.yaml").modalities:
        terms.update(modality.brands)
    return frozenset(terms)
