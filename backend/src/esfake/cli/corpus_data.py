"""Corpus data commands: add raw messages, assign splits, validate and import into Postgres."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from esfake.cli import _common
from esfake.cli._common import DEFAULT_CORPUS
from esfake.shared.config import ModelSettings
from esfake.shared.db import create_engine
from esfake.shared.modalities import load_catalog
from esfake.shared.models_config import load_models_config


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


def corpus_assign(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
    new_major: Annotated[
        bool,
        typer.Option(help="Re-cluster everything after a threshold or model change."),
    ] = False,
) -> None:
    """Give new messages their case_id, cluster and frozen split (CLAUDE.md rule 6, EF-07)."""
    from pydantic import ValidationError

    from esfake.corpus.assignment import AssignmentRequest, run_assignment
    from esfake.shared.clock import SystemClock
    from esfake.shared.config import CorpusSettings
    from esfake.shared.hmac_keys import KeyRing

    def keys() -> KeyRing:
        try:
            return KeyRing.parse(CorpusSettings().corpus_hmac_keys.get_secret_value())
        except ValidationError, ValueError:
            raise ValueError(
                "set ESFAKE_CORPUS_HMAC_KEYS to <key_id>:<secret>, with a secret of at least 16 "
                "characters (see .env.example)"
            ) from None

    def embed(texts: list[str]) -> list[list[float]]:
        return _common.local_embedder().embed(texts)

    request = AssignmentRequest(corpus, ModelSettings().config_dir, new_major)
    result = run_assignment(request, keys, embed, SystemClock())
    if result.status == "refused":
        typer.secho(f"ERROR: {result.error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if result.status == "nothing_new" or result.info is None or result.report is None:
        typer.echo("Nothing new to assign.")
        return
    report = result.report
    typer.echo(
        f"Dataset {result.info.dataset_version}: assigned "
        f"{report.new - report.discarded_synthetic} new messages "
        f"({dict(sorted(report.splits.items()))}); {report.new_clusters} new clusters, "
        f"{report.inherited} joined an existing one, {report.excluded} excluded, "
        f"{report.discarded_synthetic} synthetic discarded."
    )
    if result.threshold_needs_review:
        typer.secho(
            f"WARNING: {result.excluded} of {result.total} messages are excluded, over 5 %: "
            "review the cluster threshold (a new major dataset version).",
            fg=typer.colors.YELLOW,
            err=True,
        )
    typer.echo("Commit the corpus and dataset.json: CI only validates, it never re-assigns.")


def corpus_validate(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
) -> None:
    """Check the committed corpus: assignment, coverage and leaks (CLAUDE.md rule 6). CI runs it."""
    from collections import Counter

    from pydantic import ValidationError

    from esfake.corpus.clusters import find_leaks
    from esfake.corpus.dataset import read_corpus, read_dataset_info
    from esfake.corpus.validate import check_corpus
    from esfake.shared.thresholds import load_thresholds

    info = read_dataset_info(corpus)
    if info is None:
        typer.secho(
            "WARNING: the corpus has not been assigned yet (no dataset.json, EF-07); nothing "
            "was validated.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return
    config_dir = ModelSettings().config_dir
    try:
        records = read_corpus(corpus)
    except ValidationError as error:
        # Field names only: a validation error could otherwise echo message text.
        fields = sorted({".".join(map(str, e["loc"])) for e in error.errors()})
        typer.secho(
            f"ERROR: the corpus breaks its schema in {fields}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1) from None
    threshold = load_thresholds(config_dir).corpus.cluster_threshold
    catalog = load_catalog(config_dir / "modalities.yaml")
    report = check_corpus(
        records,
        info,
        threshold=threshold,
        embedding_model=load_models_config(config_dir).embedding.name,
        textual_modalities={m.code for m in catalog.modalities if m.kind == "textual"},
    )
    leaks = find_leaks(
        records, _common.local_embedder().embed([r.text for r in records]), threshold
    )
    report.problems += [
        f"leak: {leak.held_out} has the index neighbour {leak.index} at {leak.similarity:.3f}"
        for leak in leaks[:20]
    ]
    if len(leaks) > 20:
        report.problems.append(f"... and {len(leaks) - 20} more leaks")

    splits = Counter(str(record.split) for record in records)
    typer.echo(
        f"Dataset {info.dataset_version}: {len(records)} messages "
        f"({dict(sorted(splits.items()))}), {len(leaks)} leaks."
    )
    for warning in report.warnings:
        typer.secho(f"WARNING: {warning}", fg=typer.colors.YELLOW, err=True)
    for problem in report.problems:
        typer.secho(f"ERROR: {problem}", fg=typer.colors.RED, err=True)
    if report.problems:
        raise typer.Exit(1)
    typer.echo("Corpus valid.")


def corpus_import(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
) -> None:
    """Mirror the public corpus into Postgres with its embeddings (CLAUDE.md rule 6, EF-07)."""
    import urllib.error

    from pydantic import ValidationError

    from esfake.corpus.dataset import read_corpus, read_dataset_info
    from esfake.corpus.importer import FrozenCorpusError, import_corpus
    from esfake.pipeline.similarity.embedder import Embedder
    from esfake.pipeline.similarity.internal_client import InternalEmbedder
    from esfake.shared.clock import SystemClock
    from esfake.shared.config import CorpusImportSettings

    def fail(message: str) -> typer.Exit:
        typer.secho(f"ERROR: {message}", fg=typer.colors.RED, err=True)
        return typer.Exit(1)

    try:
        settings = CorpusImportSettings()
    except ValidationError as error:
        names = sorted({str(e["loc"][0]) for e in error.errors() if e["loc"]})
        problems = [str(e["msg"]) for e in error.errors() if not e["loc"]]
        raise fail(f"configuration: missing or invalid {names} {problems}".strip()) from None
    info = read_dataset_info(corpus)
    if info is None:
        raise fail("the corpus has not been assigned yet (no dataset.json): run corpus assign")
    embedding = load_models_config(settings.config_dir).embedding
    if info.embedding_model != embedding.name:
        raise fail(f"dataset.json was embedded with {info.embedding_model}, not {embedding.name}")
    embedder: Embedder
    if settings.internal_url is not None and settings.internal_secret is not None:
        embedder = InternalEmbedder(
            settings.internal_url, settings.internal_secret, embedding.name, embedding.dimensions
        )
    else:
        embedder = _common.local_embedder()
    records = read_corpus(corpus)

    async def run() -> None:
        engine = create_engine(settings.database_url.get_secret_value())
        try:
            async with engine.begin() as conn:
                report = await import_corpus(
                    conn,
                    records,
                    info,
                    embedder.embed,
                    actor=settings.actor,
                    now=SystemClock().now(),
                )
        finally:
            await engine.dispose()
        typer.echo(
            f"Dataset {info.dataset_version}: {report.inserted} inserted, {report.updated} "
            f"corrected, {report.deleted} deleted, {report.unchanged} unchanged."
        )

    try:
        asyncio.run(run())
    except (FrozenCorpusError, ValueError, urllib.error.URLError) as error:
        raise fail(str(error)) from None


def register(corpus_app: typer.Typer) -> None:
    corpus_app.command("add")(corpus_add)
    corpus_app.command("assign")(corpus_assign)
    corpus_app.command("validate")(corpus_validate)
    corpus_app.command("import")(corpus_import)
