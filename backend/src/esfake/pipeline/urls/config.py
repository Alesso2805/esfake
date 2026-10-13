"""The versioned URL data of config/urls.yaml (ADR-0005 §2)."""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from esfake.pipeline.urls.confusables import load_confusables
from esfake.pipeline.urls.official import OfficialBrand, official_brands
from esfake.pipeline.urls.suffixes import PublicSuffixList, load_public_suffix_list
from esfake.shared.brands import load_brands
from esfake.shared.modalities import load_catalog
from esfake.shared.thresholds import load_thresholds

type UrlSignalCode = Literal[
    "url_brand_unofficial", "url_lookalike", "url_mixed_script", "url_shortener", "url_idn"
]
URL_SIGNAL_CODES: tuple[UrlSignalCode, ...] = get_args(UrlSignalCode.__value__)


class UrlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    public_suffix_list: str
    confusables: str
    shorteners: frozenset[str] = Field(min_length=1)
    signals: dict[UrlSignalCode, float]
    brand_modalities: dict[str, str] = {}

    @model_validator(mode="after")
    def _every_signal_weighed(self) -> Self:
        missing = sorted(set(URL_SIGNAL_CODES) - set(self.signals))
        if missing:
            raise ValueError(f"config/urls.yaml gives no weight to {missing}")
        if any(weight <= 0 for weight in self.signals.values()):
            raise ValueError("URL signal weights must be positive")
        return self


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
    brands = {brand.name for brand in load_brands(config_dir).brands}
    unknown = sorted(set(config.brand_modalities) - brands)
    if unknown:
        raise ValueError(f"brand_modalities names brands not in official_domains.yaml: {unknown}")
    textual = {
        m.code
        for m in load_catalog(config_dir / "modalities.yaml").modalities
        if m.kind == "textual"
    }
    invalid = sorted(set(config.brand_modalities.values()) - textual)
    if invalid:
        raise ValueError(f"brand_modalities uses modalities that are not textual: {invalid}")
    suffixes = load_public_suffix_list(config_dir / config.public_suffix_list)
    confusables = load_confusables(config_dir / config.confusables)
    return UrlData(
        config=config,
        suffixes=suffixes,
        confusables=confusables,
        brands=official_brands(load_brands(config_dir), suffixes, confusables),
        lookalike_min_similarity=load_thresholds(config_dir).urls.lookalike_min_similarity,
    )
