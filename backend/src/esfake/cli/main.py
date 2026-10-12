"""Entry point for the `esfake` CLI: composes the command groups of the other modules."""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from esfake.pipeline.similarity.embedder import FastEmbedEmbedder

from esfake.cli import evaluation, rules, serving
from esfake.cli._common import DEFAULT_CORPUS
from esfake.shared.config import ModelSettings
from esfake.shared.db import create_engine
from esfake.shared.modalities import load_catalog
from esfake.shared.models_config import load_models_config

app = typer.Typer(no_args_is_help=True, help="¿EsFake? command-line tools.")
evaluation.register(app)
serving.register(app)
rules.register(app)

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
