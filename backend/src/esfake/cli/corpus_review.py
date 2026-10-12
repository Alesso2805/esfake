"""Corpus review commands: sample pairs, set the cluster threshold and compare embedding models."""

from pathlib import Path
from typing import Annotated

import typer

from esfake.cli import _common
from esfake.cli._common import DEFAULT_CORPUS
from esfake.shared.config import ModelSettings
from esfake.shared.models_config import load_models_config

DEFAULT_PAIRS = Path("../evals/datasets/cluster_pairs.csv")


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
    similarities = cosine_matrix(_common.local_embedder().embed(texts))
    has_contender = load_models_config(ModelSettings().config_dir).embedding_contender is not None
    if contender and has_contender:
        other = cosine_matrix(_common.local_embedder(contender=True).embed(texts))
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
    similarities = cosine_matrix(_common.local_embedder().embed([by_ref[ref].text for ref in refs]))
    index = {ref: position for position, ref in enumerate(refs)}
    scored = [(float(similarities[index[p.ref_a], index[p.ref_b]]), p.same) for p in labeled]
    choice = choose_threshold(scored)
    typer.echo(
        f"{choice.pairs} pairs, {choice.same} labelled 'same'. Recommended cluster threshold: "
        f"{choice.threshold} (F1 {choice.f1:.2f}, agreement {choice.accuracy:.0%}). Record it as "
        f"corpus.cluster_threshold in config/thresholds.yaml before assigning splits."
    )


DEFAULT_COMPARISON = Path("../docs/evals/embedding-comparison.json")


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
        embedder = _common.local_embedder(contender=contender)
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


def register(corpus_app: typer.Typer) -> None:
    corpus_app.command("pairs")(corpus_pairs)
    corpus_app.command("threshold")(corpus_threshold)
    corpus_app.command("compare-models")(corpus_compare_models)
