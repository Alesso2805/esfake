"""Seeds the `modalities` table from the catalogue in config/modalities.yaml."""

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from esfake.shared.db.models import Modality
from esfake.shared.modalities import ModalityCatalog


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
