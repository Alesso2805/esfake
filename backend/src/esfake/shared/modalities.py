"""Modality catalogue read from config/modalities.yaml: the same codes in every environment."""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModalitySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["textual", "guidance_only"]
    name_es: str = Field(min_length=1)
    name_en: str = Field(min_length=1)
    # Brand names tied to the modality; exempt from name redaction, not stored in the table.
    brands: tuple[str, ...] = ()


class ModalityCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    modalities: list[ModalitySpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _codes_are_unique(self) -> Self:
        codes = [modality.code for modality in self.modalities]
        if len(codes) != len(set(codes)):
            raise ValueError("modality codes must be unique")
        return self


def load_catalog(path: Path) -> ModalityCatalog:
    return ModalityCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
