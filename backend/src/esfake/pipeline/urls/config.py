"""The versioned URL data of config/urls.yaml (ADR-0005 §2)."""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from esfake.pipeline.urls.confusables import load_confusables
from esfake.pipeline.urls.official import OfficialBrand, official_brands
from esfake.pipeline.urls.suffixes import PublicSuffixList, load_public_suffix_list
from esfake.shared.brands import load_brands
from esfake.shared.thresholds import load_thresholds


class UrlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    public_suffix_list: str
    confusables: str
    shorteners: frozenset[str] = Field(min_length=1)


class UrlData(BaseModel):
    """The configuration with its data files loaded, ready for analysis."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    config: UrlConfig
    suffixes: PublicSuffixList
    confusables: Mapping[str, str]
    brands: tuple[OfficialBrand, ...]
    lookalike_min_similarity: float


@lru_cache(maxsize=4)
def load_url_data(config_dir: Path) -> UrlData:
    path = config_dir / "urls.yaml"
    config = UrlConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    suffixes = load_public_suffix_list(config_dir / config.public_suffix_list)
    confusables = load_confusables(config_dir / config.confusables)
    return UrlData(
        config=config,
        suffixes=suffixes,
        confusables=confusables,
        brands=official_brands(load_brands(config_dir), suffixes, confusables),
        lookalike_min_similarity=load_thresholds(config_dir).urls.lookalike_min_similarity,
    )
