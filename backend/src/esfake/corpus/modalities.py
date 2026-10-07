"""Modality catalogue, seeded from config/modalities.yaml with the same codes everywhere."""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from esfake.shared.db.models import Modality


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


async def sync_modalities(engine: AsyncEngine, catalog: ModalityCatalog) -> None:
    """Upsert every listed modality and deactivate the ones no longer listed.

    Rows are never deleted: verdicts and corpus messages keep pointing at old codes.
    """
    async with engine.begin() as conn:
        for spec in catalog.modalities:
            values = spec.model_dump(exclude={"brands"})
            statement = insert(Modality).values(**values, is_active=True)
            await conn.execute(
                statement.on_conflict_do_update(
                    index_elements=[Modality.code],
                    set_={**values, "is_active": True},
                )
            )
        listed = [spec.code for spec in catalog.modalities]
        await conn.execute(
            update(Modality).where(Modality.code.not_in(listed)).values(is_active=False)
        )
