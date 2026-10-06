"""Entry point for the `esfake` CLI.

`eval`, `eval-record` and `redteam` are stubs until their stories land: they print a
warning and exit 0 so `make` targets and CI can call them from Sprint 0 on.
"""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from esfake.corpus.modalities import ModalityCatalog, load_catalog, sync_modalities
from esfake.shared.config import ApiSettings, MigrationSettings, ModelSettings
from esfake.shared.db import create_engine
from esfake.shared.models_config import load_models_config

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


@app.command()
def serve() -> None:
    """Run the API: public and internal listeners on one event loop (CLAUDE.md rule 9)."""
    # Imported here so the other commands never load FastAPI or the model runtime.
    from esfake.api.serve import serve as serve_api
    from esfake.pipeline.similarity.embedder import FastEmbedEmbedder
    from esfake.shared.logging import configure_logging

    configure_logging()
    settings = ApiSettings()
    embedding = load_models_config(settings.config_dir).embedding

    def load_embedder() -> FastEmbedEmbedder:
        return FastEmbedEmbedder(
            embedding.name,
            embedding.dimensions,
            settings.models_dir,
            offline=settings.models_offline,
        )

    asyncio.run(serve_api(settings, load_embedder))


@app.command("download-models")
def download_models() -> None:
    """Download the model weights listed in config/models.yaml into ESFAKE_MODELS_DIR."""
    from esfake.pipeline.similarity.embedder import download_model

    settings = ModelSettings()
    embedding = load_models_config(settings.config_dir).embedding
    download_model(embedding.name, settings.models_dir)
    typer.echo(f"Downloaded {embedding.name} into {settings.models_dir}.")
