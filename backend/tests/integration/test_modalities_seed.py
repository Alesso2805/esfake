import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine
from typer.testing import CliRunner

from esfake.cli.main import app
from esfake.corpus.modalities import sync_modalities
from esfake.shared.db.models import Modality
from esfake.shared.modalities import ModalityCatalog, load_catalog
from tests.integration.conftest import Database
from tests.paths import MODALITIES_YAML


async def _active_by_code(engine: AsyncEngine) -> dict[str, bool]:
    async with engine.connect() as conn:
        rows = await conn.execute(select(Modality.code, Modality.is_active))
        return dict(rows.all())


async def test_seed_is_idempotent_and_readable_by_the_app_role(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    catalog = load_catalog(MODALITIES_YAML)

    await sync_modalities(owner_engine, catalog)
    await sync_modalities(owner_engine, catalog)

    expected = {modality.code: True for modality in catalog.modalities}
    assert await _active_by_code(app_engine) == expected


async def test_unlisted_modalities_are_deactivated_not_deleted(owner_engine: AsyncEngine) -> None:
    full = load_catalog(MODALITIES_YAML)
    dropped = full.modalities[-1].code

    await sync_modalities(owner_engine, ModalityCatalog(modalities=full.modalities[:-1]))
    assert (await _active_by_code(owner_engine))[dropped] is False

    await sync_modalities(owner_engine, full)
    assert (await _active_by_code(owner_engine))[dropped] is True


def test_cli_seeds_from_the_catalogue_file(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", database.owner_url)

    result = CliRunner().invoke(app, ["seed-modalities", str(MODALITIES_YAML)])

    assert result.exit_code == 0, result.output
    assert "Seeded 9 modalities." in result.stdout
