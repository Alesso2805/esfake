"""Subcategories of legitimate messages, from config/subcategories.yaml (EF-07, EF-09)."""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SubcategorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    hard_negative: bool
    description: str = Field(min_length=1)


class SubcategoryCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subcategories: tuple[SubcategorySpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _codes_are_unique(self) -> Self:
        codes = [subcategory.code for subcategory in self.subcategories]
        if len(codes) != len(set(codes)):
            raise ValueError("subcategory codes must be unique")
        return self

    @property
    def codes(self) -> frozenset[str]:
        return frozenset(subcategory.code for subcategory in self.subcategories)


def load_subcategories(path: Path) -> SubcategoryCatalog:
    return SubcategoryCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
