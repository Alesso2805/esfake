"""The versioned URL data of config/urls.yaml (ADR-0005 §2)."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from esfake.pipeline.urls.suffixes import PublicSuffixList, load_public_suffix_list


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


@lru_cache(maxsize=4)
def load_url_data(config_dir: Path) -> UrlData:
    path = config_dir / "urls.yaml"
    config = UrlConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return UrlData(
        config=config,
        suffixes=load_public_suffix_list(config_dir / config.public_suffix_list),
    )
