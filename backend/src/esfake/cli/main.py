"""Entry point for the `esfake` CLI.

`eval`, `eval-record` and `redteam` are stubs until their stories land: they print a
warning and exit 0 so `make` targets and CI can call them from Sprint 0 on.
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from esfake.corpus.modalities import ModalityCatalog, load_catalog, sync_modalities
from esfake.shared.config import MigrationSettings
from esfake.shared.db import create_engine

app = typer.Typer(no_args_is_help=True, help="¿EsFake? command-line tools.")


def _warn_stub(command: str, story: str) -> None:
    typer.secho(
        f"WARNING: `esfake {command}` is a stub until {story}; nothing was evaluated.",
        fg=typer.colors.YELLOW,
        err=True,
    )


@app.command("eval")
def eval_() -> None:
    """Run the evaluation gate on `eval` in cached-strict mode (EF-08)."""
    _warn_stub("eval", "EF-08")


@app.command("eval-record")
def eval_record() -> None:
    """Record missing model responses into the evaluation cache (EF-08)."""
    _warn_stub("eval-record", "EF-08")


@app.command()
def redteam() -> None:
    """Run the `redteam/dev` attack suite (EF-17)."""
    _warn_stub("redteam", "EF-17")


@app.command("seed-modalities")
def seed_modalities(
    catalog: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="Path to config/modalities.yaml.")
    ],
) -> None:
    """Upsert the modality catalogue as esfake_owner (MIGRATIONS_DATABASE_URL)."""
    loaded = load_catalog(catalog)
    asyncio.run(_seed_modalities(loaded))
    typer.echo(f"Seeded {len(loaded.modalities)} modalities.")


async def _seed_modalities(catalog: ModalityCatalog) -> None:
    engine = create_engine(MigrationSettings().migrations_database_url.get_secret_value())
    try:
        await sync_modalities(engine, catalog)
    finally:
        await engine.dispose()
