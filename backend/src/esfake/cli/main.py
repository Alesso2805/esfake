"""Entry point for the `esfake` CLI.

`redteam` is a stub until EF-17: it prints a warning and exits 0 so `make redteam` and CI can
call it from Sprint 0 on.
"""

import asyncio
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from esfake.pipeline.llm.cache import CacheMode
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


DEFAULT_CORPUS = Path("../evals/datasets/corpus.jsonl")
DEFAULT_EVALS = Path("../docs/evals")
DEFAULT_LLM_CACHE = Path("../evals/llm_cache")
# ADR-0003: budget of one `make eval-record` run.
EVAL_RECORD_BUDGET_USD = 5.0


def _git_sha() -> str:
    """The commit under evaluation, with `-dirty` when the working tree has changes."""
    git = shutil.which("git")
    if git is None:
        return "unknown"

    def run(*args: str) -> str:
        # Fixed arguments to the git found on PATH; no user input reaches the command.
        result = subprocess.run([git, *args], capture_output=True, text=True, check=True)  # noqa: S603
        return result.stdout.strip()

    sha = run("rev-parse", "HEAD")
    return f"{sha}-dirty" if run("status", "--porcelain") else sha


def _evaluate(
    mode: CacheMode,
    corpus: Path,
    evals_dir: Path,
    llm_cache: Path,
    *,
    budget_usd: Decimal | None = None,
    publish_as: str | None = None,
) -> None:
    from esfake.corpus.dataset import read_corpus
    from esfake.corpus.subcategories import load_subcategories
    from esfake.evaluation.gate import run_gate
    from esfake.evaluation.harness import run_cases, split_cases
    from esfake.evaluation.metrics import compute_metrics
    from esfake.evaluation.published import latest_published, publish
    from esfake.evaluation.report import format_report
    from esfake.pipeline.llm.cache import BudgetExceededError, MissingResponseError, ResponseCache
    from esfake.pipeline.manifest import build_manifest
    from esfake.pipeline.redaction import build_redactor
    from esfake.pipeline.verifier import build_pipeline
    from esfake.shared.clock import SystemClock
    from esfake.shared.thresholds import load_thresholds

    config_dir = ModelSettings().config_dir
    records = read_corpus(corpus)
    cases = split_cases(records, "eval")
    if not cases:
        typer.secho(
            "WARNING: the corpus has no `eval` cases yet (`esfake corpus assign`, EF-07); "
            "nothing was evaluated.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        return
    index_ids = [r.case_id for r in split_cases(records, "index") if r.case_id is not None]
    manifest = build_manifest(config_dir, _git_sha(), index_ids)
    cache = ResponseCache(llm_cache, mode, budget_usd)
    pipeline = build_pipeline(config_dir, cache)
    try:
        predictions = asyncio.run(run_cases(cases, build_redactor(config_dir), pipeline))
    except (MissingResponseError, BudgetExceededError) as error:
        typer.secho(f"ERROR: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None

    metrics = compute_metrics(predictions)
    published = latest_published(evals_dir)
    hard_negatives = frozenset(
        s.code
        for s in load_subcategories(config_dir / "subcategories.yaml").subcategories
        if s.hard_negative
    )
    gate = run_gate(
        predictions,
        published.baseline() if published is not None else None,
        load_thresholds(config_dir).evaluation,
        hard_negatives,
    )
    typer.echo(format_report(mode, manifest.hash, metrics, gate))
    if mode == "record":
        typer.echo(
            f"Recorded {cache.live_calls} responses live for US${cache.spent_usd}; "
            f"commit {llm_cache} with the PR."
        )
    if not gate.passed:
        raise typer.Exit(1)
    if publish_as is not None:
        if manifest.git_sha.endswith("-dirty") or manifest.git_sha == "unknown":
            typer.secho(
                "ERROR: commit every change before publishing, so the manifest names the code.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)
        try:
            path = publish(
                evals_dir, publish_as, SystemClock().now().date(), manifest, metrics, predictions
            )
        except ValueError as error:
            typer.secho(f"ERROR: {error}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from None
        typer.echo(f"Published {publish_as} to {path}; commit it.")


@app.command("eval")
def eval_(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
    evals_dir: Annotated[Path, typer.Option(help="Published versions.")] = DEFAULT_EVALS,
    llm_cache: Annotated[Path, typer.Option(help="Recorded model responses.")] = DEFAULT_LLM_CACHE,
    publish: Annotated[
        str | None, typer.Option(help="Publish this run as a version: v0, v0.1... v1.0.")
    ] = None,
) -> None:
    """Run the gate on `eval` in cached-strict mode against the latest published version."""
    _evaluate("cached_strict", corpus, evals_dir, llm_cache, publish_as=publish)


@app.command("eval-record")
def eval_record(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
    evals_dir: Annotated[Path, typer.Option(help="Published versions.")] = DEFAULT_EVALS,
    llm_cache: Annotated[Path, typer.Option(help="Recorded model responses.")] = DEFAULT_LLM_CACHE,
    budget: Annotated[float, typer.Option(help="Spending cap in US$.")] = EVAL_RECORD_BUDGET_USD,
) -> None:
    """Record missing model responses within a budget, then run the gate without them."""
    _evaluate("record", corpus, evals_dir, llm_cache, budget_usd=Decimal(str(budget)))


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
        return FastEmbedEmbedder(embedding, settings.models_dir, offline=settings.models_offline)

    asyncio.run(serve_api(settings, load_embedder, load_redactor))


@app.command("download-models")
def download_models() -> None:
    """Download the model weights listed in config/models.yaml into ESFAKE_MODELS_DIR."""
    from esfake.pipeline.similarity.embedder import download_model

    settings = ModelSettings()
    embedding = load_models_config(settings.config_dir).embedding
    download_model(embedding, settings.models_dir)
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


def _local_embedder(contender: bool = False) -> FastEmbedEmbedder:
    """In development and CI the CLI loads the model itself; production uses /internal/embed.

    `contender` loads the model the EF-07 checkpoint compares against (ADR-0003, amendment 1).
    """
    from esfake.pipeline.similarity.embedder import FastEmbedEmbedder

    settings = ModelSettings()
    models = load_models_config(settings.config_dir)
    config = models.embedding_contender if contender else models.embedding
    if config is None:
        raise typer.BadParameter("config/models.yaml names no embedding_contender")
    return FastEmbedEmbedder(config, settings.models_dir, offline=settings.models_offline)


@corpus_app.command("pairs")
def corpus_pairs(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
    out: Annotated[Path, typer.Option(help="Spreadsheet to label.")] = DEFAULT_PAIRS,
    per_bin: Annotated[int, typer.Option(help="Pairs per similarity bin (10 bins).")] = 10,
    low: Annotated[float, typer.Option(help="Lowest similarity sampled.")] = 0.70,
    high: Annotated[float, typer.Option(help="Highest similarity sampled.")] = 0.98,
    contender: Annotated[
        bool, typer.Option(help="Take half the pairs near the contender model's cut too.")
    ] = True,
) -> None:
    """Sample pairs around the likely cluster threshold for manual review (ADR-0003 §6).

    With the contender of config/models.yaml, half the pairs sit near each model's cut, so the
    same labels serve the embedding checkpoint and the threshold of whichever model wins
    (ADR-0003, amendment 1).
    """
    from esfake.corpus.clusters import cosine_matrix
    from esfake.corpus.dataset import read_corpus
    from esfake.corpus.pairs import matched_range, merge_pairs, select_review_pairs, write_pairs

    records = read_corpus(corpus)
    if len(records) < 2:
        typer.secho("ERROR: the corpus needs at least two messages", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    texts = [record.text for record in records]
    similarities = cosine_matrix(_local_embedder().embed(texts))
    has_contender = load_models_config(ModelSettings().config_dir).embedding_contender is not None
    if contender and has_contender:
        other = cosine_matrix(_local_embedder(contender=True).embed(texts))
        other_low, other_high = matched_range(similarities, other, low, high)
        half = max(1, per_bin // 2)
        pairs = merge_pairs(
            select_review_pairs(records, similarities, low=low, high=high, per_bin=half),
            select_review_pairs(records, other, low=other_low, high=other_high, per_bin=half),
        )
        typer.echo(f"Contender range matched by rank: {other_low:.3f} to {other_high:.3f}.")
    else:
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


@corpus_app.command("assign")
def corpus_assign(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
    new_major: Annotated[
        bool,
        typer.Option(help="Re-cluster everything after a threshold or model change."),
    ] = False,
) -> None:
    """Give new messages their case_id, cluster and frozen split (CLAUDE.md rule 6, EF-07)."""
    from pydantic import ValidationError

    from esfake.corpus.assign import (
        DatasetVersionError,
        assign,
        next_dataset_info,
        unassigned,
    )
    from esfake.corpus.dataset import (
        read_corpus,
        read_dataset_info,
        write_corpus,
        write_dataset_info,
    )
    from esfake.corpus.validate import EXCLUDED_REVIEW_SHARE
    from esfake.shared.clock import SystemClock
    from esfake.shared.config import CorpusSettings
    from esfake.shared.hmac_keys import KeyRing
    from esfake.shared.thresholds import load_thresholds

    def fail(message: str) -> typer.Exit:
        typer.secho(f"ERROR: {message}", fg=typer.colors.RED, err=True)
        return typer.Exit(1)

    config_dir = ModelSettings().config_dir
    cut = load_thresholds(config_dir).corpus
    if not cut.cluster_threshold_reviewed:
        raise fail(
            "the cluster threshold is still provisional. Review pairs with `esfake corpus pairs` "
            "and `esfake corpus threshold`, record the value in config/thresholds.yaml and set "
            "cluster_threshold_reviewed: true (ADR-0003, section 6)."
        )
    model = load_models_config(config_dir).embedding.name
    previous = read_dataset_info(corpus)
    records = read_corpus(corpus)
    if new_major:
        records = unassigned(records)
    if all(record.split is not None for record in records):
        typer.echo("Nothing new to assign.")
        return
    try:
        keys = KeyRing.parse(CorpusSettings().corpus_hmac_keys.get_secret_value())
    except ValidationError, ValueError:
        raise fail(
            "set ESFAKE_CORPUS_HMAC_KEYS to <key_id>:<secret>, with a secret of at least 16 "
            "characters (see .env.example)"
        ) from None
    try:
        info = next_dataset_info(
            previous, threshold=cut.cluster_threshold, embedding_model=model, new_major=new_major
        )
    except DatasetVersionError as error:
        raise fail(str(error)) from None

    vectors = _local_embedder().embed([record.text for record in records])
    today = SystemClock().now().date()
    try:
        result, report = assign(records, vectors, cut.cluster_threshold, keys, today)
    except ValueError as error:
        raise fail(str(error)) from None
    info = info.model_copy(
        update={"discarded_synthetic": info.discarded_synthetic + report.discarded_synthetic}
    )
    write_corpus(corpus, result)
    write_dataset_info(corpus, info)
    typer.echo(
        f"Dataset {info.dataset_version}: assigned {report.new - report.discarded_synthetic} new "
        f"messages ({dict(sorted(report.splits.items()))}); {report.new_clusters} new clusters, "
        f"{report.inherited} joined an existing one, {report.excluded} excluded, "
        f"{report.discarded_synthetic} synthetic discarded."
    )
    excluded = sum(record.split == "excluded" for record in result)
    if result and excluded / len(result) > EXCLUDED_REVIEW_SHARE:
        typer.secho(
            f"WARNING: {excluded} of {len(result)} messages are excluded, over 5 %: review the "
            "cluster threshold (a new major dataset version).",
            fg=typer.colors.YELLOW,
            err=True,
        )
    typer.echo("Commit the corpus and dataset.json: CI only validates, it never re-assigns.")


@corpus_app.command("validate")
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
    leaks = find_leaks(records, _local_embedder().embed([r.text for r in records]), threshold)
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


@corpus_app.command("import")
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
        embedder = _local_embedder()
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


DEFAULT_COMPARISON = Path("../docs/evals/embedding-comparison.json")


@corpus_app.command("compare-models")
def corpus_compare_models(
    pairs: Annotated[Path, typer.Option(exists=True, help="Labelled pairs.")] = DEFAULT_PAIRS,
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
    out: Annotated[Path, typer.Option(help="Where the evidence is written.")] = (
        DEFAULT_COMPARISON
    ),
) -> None:
    """Compare the deployed embedding model with the contender (ADR-0003, amendment 1)."""
    from esfake.corpus.clusters import cosine_matrix
    from esfake.corpus.dataset import read_corpus
    from esfake.corpus.pairs import read_labeled_pairs, record_ref
    from esfake.evaluation.embedding_comparison import ModelMeasures, compare, measure_latencies
    from esfake.shared.clock import SystemClock

    try:
        labeled = read_labeled_pairs(pairs)
    except ValueError as error:
        typer.secho(f"ERROR: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None
    records = read_corpus(corpus)
    by_ref = {record_ref(record): record for record in records}
    refs = sorted({ref for pair in labeled for ref in (pair.ref_a, pair.ref_b)})
    unknown = [ref for ref in refs if ref not in by_ref]
    if unknown:
        typer.secho(f"ERROR: pairs refer to texts not in the corpus: {unknown}", err=True)
        raise typer.Exit(1)
    texts = [by_ref[ref].text for ref in refs]
    position = {ref: i for i, ref in enumerate(refs)}

    settings = ModelSettings()
    models = load_models_config(settings.config_dir)

    def measure(contender: bool) -> ModelMeasures:
        config = models.embedding_contender if contender else models.embedding
        if config is None:
            raise typer.BadParameter("config/models.yaml names no embedding_contender")
        embedder = _local_embedder(contender=contender)
        similarities = cosine_matrix(embedder.embed(texts))
        return ModelMeasures(
            name=embedder.model_name,
            scores=[float(similarities[position[p.ref_a], position[p.ref_b]]) for p in labeled],
            latencies_ms=measure_latencies(
                config, settings.models_dir, texts, offline=settings.models_offline
            ),
            token_counts=embedder.token_counts([record.text for record in records]),
            max_tokens=embedder.max_tokens,
        )

    result = compare(
        measure(contender=False),
        measure(contender=True),
        [pair.same for pair in labeled],
        SystemClock().now().date(),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(result.model_dump_json(indent=2) + "\n")

    typer.echo(f"Embedding checkpoint on {result.pairs} labelled pairs ({result.same} 'same'):")
    typer.echo(
        f"  {'model':<60} {'AUC':>6} {'cut':>6} {'F1':>5} {'p95 ms':>7} {'>128':>6} {'>512':>6}"
    )
    for model in (result.deployed, result.contender):
        typer.echo(
            f"  {model.name:<60} {model.auc:>6.3f} {model.threshold:>6.3f} {model.f1:>5.2f} "
            f"{model.latency_ms_p95:>7.1f} {model.share_over[128]:>6.1%} "
            f"{model.share_over[512]:>6.1%}"
        )
    gain = result.auc_difference
    typer.echo(
        f"AUC gain of the contender: {gain.difference:+.3f}, 95 % interval [{gain.low:+.3f}, "
        f"{gain.high:+.3f}] ({gain.resamples} paired resamples)."
    )
    winner = result.contender.name if result.switch else result.deployed.name
    typer.echo(f"Decision: {winner} ({'; '.join(result.reasons)}).")
    typer.echo(f"Wrote {out}; record the result in ADR-0003, amendment 2.")
