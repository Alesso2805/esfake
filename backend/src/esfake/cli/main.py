"""Entry point for the `esfake` CLI.

`eval`, `eval-record` and `redteam` are stubs until their stories land: they print a
warning and exit 0 so `make` targets and CI can call them from Sprint 0 on.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from esfake.pipeline.similarity.embedder import FastEmbedEmbedder

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
    from esfake.pipeline.redaction import Redactor, build_redactor
    from esfake.pipeline.similarity.embedder import FastEmbedEmbedder
    from esfake.shared.logging import configure_logging

    configure_logging()
    settings = ApiSettings()
    embedding = load_models_config(settings.config_dir).embedding

    def load_redactor() -> Redactor:
        return build_redactor(settings.config_dir)

    def load_embedder() -> FastEmbedEmbedder:
        return FastEmbedEmbedder(
            embedding.name,
            embedding.dimensions,
            settings.models_dir,
            offline=settings.models_offline,
        )

    asyncio.run(serve_api(settings, load_embedder, load_redactor))


@app.command("download-models")
def download_models() -> None:
    """Download the model weights listed in config/models.yaml into ESFAKE_MODELS_DIR."""
    from esfake.pipeline.similarity.embedder import download_model

    settings = ModelSettings()
    embedding = load_models_config(settings.config_dir).embedding
    download_model(embedding.name, settings.models_dir)
    typer.echo(f"Downloaded {embedding.name} into {settings.models_dir}.")


worker_app = typer.Typer(no_args_is_help=True, help="Background workers.")
app.add_typer(worker_app, name="worker")


@worker_app.command("channels")
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


@worker_app.command("maintenance")
def worker_maintenance() -> None:
    """Run the periodic maintenance jobs with the system clock."""
    from esfake.shared.clock import SystemClock
    from esfake.shared.logging import configure_logging
    from esfake.workers import run_until_signal
    from esfake.workers.maintenance import MaintenanceWorker

    configure_logging()
    asyncio.run(run_until_signal(MaintenanceWorker(SystemClock(), jobs=()).run))


@app.command("redaction-report")
def redaction_report(
    dataset: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Labelled names (JSONL).")
    ] = Path("../evals/redaction/names_validation.jsonl"),
    model: Annotated[
        str | None, typer.Option(help="spaCy model; defaults to config/models.yaml.")
    ] = None,
) -> None:
    """Measure name-redaction recall against the floor, and brand survival (ADR-0004 §2)."""
    import dataclasses
    import json

    from esfake.evaluation.redaction import evaluate, load_cases
    from esfake.pipeline.redaction.names import SpacyNameFinder
    from esfake.shared.brands import exempt_terms
    from esfake.shared.thresholds import load_thresholds

    settings = ModelSettings()
    name = model or load_models_config(settings.config_dir).spacy.name
    if name is None:
        raise typer.BadParameter("config/models.yaml names no spaCy model; pass --model")
    finder = SpacyNameFinder(name, exempt_terms(settings.config_dir))
    report = evaluate(finder, load_cases(dataset))
    floor = load_thresholds(settings.config_dir).redaction.name_recall_floor
    summary = {
        "model": name,
        "dataset": str(dataset),
        "name_recall_floor": floor,
        "meets_floor": report.recall >= floor,
        **dataclasses.asdict(report),
    }
    typer.echo(json.dumps(summary, indent=2))


corpus_app = typer.Typer(no_args_is_help=True, help="Public corpus: add, review pairs, assign.")
app.add_typer(corpus_app, name="corpus")

DEFAULT_CORPUS = Path("../evals/datasets/corpus.jsonl")


@corpus_app.command("add")
def corpus_add(
    raw: Annotated[
        Path,
        typer.Argument(
            exists=True, dir_okay=False, help="CSV or JSONL of raw messages, outside the repo."
        ),
    ],
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL to append to.")] = DEFAULT_CORPUS,
) -> None:
    """Redact raw messages and append them to the public corpus (EF-07, EF-09)."""
    from esfake.corpus.add import CorpusInputError, add_messages, load_raw_rows
    from esfake.corpus.subcategories import load_subcategories
    from esfake.pipeline.redaction import build_redactor
    from esfake.shared.clock import SystemClock

    settings = ModelSettings()
    catalog = load_catalog(settings.config_dir / "modalities.yaml")
    try:
        rows = load_raw_rows(
            raw,
            settings.config_dir.resolve().parent,
            catalog,
            load_subcategories(settings.config_dir / "subcategories.yaml"),
        )
    except CorpusInputError as error:
        typer.secho(f"ERROR: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None
    report = add_messages(rows, corpus, build_redactor(settings.config_dir), SystemClock())
    typer.echo(
        f"Added {report.added} messages, skipped {report.duplicates} duplicates. "
        f"Redacted: {dict(sorted(report.redactions.items()))}."
    )
    typer.echo("Review the new lines with `git diff` before committing: redaction is not perfect.")


DEFAULT_PAIRS = Path("../evals/datasets/cluster_pairs.csv")


def _local_embedder() -> FastEmbedEmbedder:
    """In development and CI the CLI loads the model itself; production uses /internal/embed."""
    from esfake.pipeline.similarity.embedder import FastEmbedEmbedder

    settings = ModelSettings()
    embedding = load_models_config(settings.config_dir).embedding
    return FastEmbedEmbedder(
        embedding.name, embedding.dimensions, settings.models_dir, offline=settings.models_offline
    )


@corpus_app.command("pairs")
def corpus_pairs(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
    out: Annotated[Path, typer.Option(help="Spreadsheet to label.")] = DEFAULT_PAIRS,
    per_bin: Annotated[int, typer.Option(help="Pairs per similarity bin (10 bins).")] = 10,
    low: Annotated[float, typer.Option(help="Lowest similarity sampled.")] = 0.70,
    high: Annotated[float, typer.Option(help="Highest similarity sampled.")] = 0.98,
) -> None:
    """Sample pairs around the likely cluster threshold for manual review (ADR-0003 §6)."""
    from esfake.corpus.clusters import cosine_matrix
    from esfake.corpus.dataset import read_corpus
    from esfake.corpus.pairs import select_review_pairs, write_pairs

    records = read_corpus(corpus)
    if len(records) < 2:
        typer.secho("ERROR: the corpus needs at least two messages", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    similarities = cosine_matrix(_local_embedder().embed([record.text for record in records]))
    pairs = select_review_pairs(records, similarities, low=low, high=high, per_bin=per_bin)
    write_pairs(out, pairs)
    typer.echo(
        f"Wrote {len(pairs)} pairs to {out}. In the 'same' column write 'si' when both texts are "
        f"the same message or a near-duplicate variant, 'no' otherwise; then run "
        f"`esfake corpus threshold`."
    )


@corpus_app.command("threshold")
def corpus_threshold(
    pairs: Annotated[Path, typer.Option(exists=True, help="Labelled pairs.")] = DEFAULT_PAIRS,
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
) -> None:
    """Recommend the cluster threshold from the labelled pairs (ADR-0003 §6)."""
    from esfake.corpus.clusters import cosine_matrix
    from esfake.corpus.dataset import read_corpus
    from esfake.corpus.pairs import choose_threshold, read_labeled_pairs, record_ref

    labeled = read_labeled_pairs(pairs)
    by_ref = {record_ref(record): record for record in read_corpus(corpus)}
    refs = sorted({ref for pair in labeled for ref in (pair.ref_a, pair.ref_b)})
    unknown = [ref for ref in refs if ref not in by_ref]
    if unknown:
        typer.secho(f"ERROR: pairs refer to texts not in the corpus: {unknown}", err=True)
        raise typer.Exit(1)
    similarities = cosine_matrix(_local_embedder().embed([by_ref[ref].text for ref in refs]))
    index = {ref: position for position, ref in enumerate(refs)}
    scored = [(float(similarities[index[p.ref_a], index[p.ref_b]]), p.same) for p in labeled]
    choice = choose_threshold(scored)
    typer.echo(
        f"{choice.pairs} pairs, {choice.same} labelled 'same'. Recommended cluster threshold: "
        f"{choice.threshold} (F1 {choice.f1:.2f}, agreement {choice.accuracy:.0%}). Record it as "
        f"corpus.cluster_threshold in config/thresholds.yaml before assigning splits."
    )
