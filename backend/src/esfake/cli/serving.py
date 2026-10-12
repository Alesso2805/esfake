"""Service commands: seed the modalities, run the API, download models and run the workers."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from esfake.corpus.modalities import sync_modalities
from esfake.shared.config import ApiSettings, MigrationSettings, ModelSettings
from esfake.shared.db import create_engine
from esfake.shared.modalities import ModalityCatalog, load_catalog
from esfake.shared.models_config import load_models_config


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


def serve() -> None:
    """Run the API: public and internal listeners on one event loop (CLAUDE.md rule 9)."""
    # Imported here so the other commands never load FastAPI or the model runtime.
    from esfake.api.serve import serve as serve_api
    from esfake.pipeline.redaction import Redactor, build_redactor
    from esfake.pipeline.similarity.embedder import FastEmbedEmbedder
    from esfake.shared.logging import configure_logging

    configure_logging()
    settings = ApiSettings()
    embedding = load_models_config(settings.config_dir).embedding

    def load_redactor() -> Redactor:
        return build_redactor(settings.config_dir)

    def load_embedder() -> FastEmbedEmbedder:
        return FastEmbedEmbedder(embedding, settings.models_dir, offline=settings.models_offline)

    asyncio.run(serve_api(settings, load_embedder, load_redactor))


def download_models() -> None:
    """Download the model weights listed in config/models.yaml into ESFAKE_MODELS_DIR."""
    from esfake.pipeline.similarity.embedder import download_model

    settings = ModelSettings()
    embedding = load_models_config(settings.config_dir).embedding
    download_model(embedding, settings.models_dir)
    typer.echo(f"Downloaded {embedding.name} into {settings.models_dir}.")


def worker_channels() -> None:
    """Wake on queue notifications over a direct connection (ADR-0002 §2)."""
    from esfake.shared.config import ChannelWorkerSettings
    from esfake.shared.logging import configure_logging
    from esfake.workers import run_until_signal
    from esfake.workers.channels import ChannelWorker, asyncpg_dsn, log_wake

    configure_logging()
    settings = ChannelWorkerSettings()
    worker = ChannelWorker(asyncpg_dsn(settings.database_direct_url.get_secret_value()), log_wake)
    asyncio.run(run_until_signal(worker.run))


def worker_maintenance() -> None:
    """Run the periodic maintenance jobs with the system clock."""
    from esfake.shared.clock import SystemClock
    from esfake.shared.logging import configure_logging
    from esfake.workers import run_until_signal
    from esfake.workers.maintenance import MaintenanceWorker

    configure_logging()
    asyncio.run(run_until_signal(MaintenanceWorker(SystemClock(), jobs=()).run))


def register(app: typer.Typer) -> None:
    app.command("seed-modalities")(seed_modalities)
    app.command("serve")(serve)
    app.command("download-models")(download_models)
    worker_app = typer.Typer(no_args_is_help=True, help="Background workers.")
    worker_app.command("channels")(worker_channels)
    worker_app.command("maintenance")(worker_maintenance)
    app.add_typer(worker_app, name="worker")
