"""Similarity layer commands: calibrate k and delta on `eval` (ADR-0003 §6, EF-13)."""

from pathlib import Path
from typing import Annotated

import typer

from esfake.cli import _common
from esfake.cli._common import DEFAULT_CORPUS
from esfake.shared.config import ModelSettings


def similarity_calibrate(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
) -> None:
    """Recommend k and delta for the similarity layer from the `eval` split."""
    from esfake.evaluation.similarity_calibration import run_calibration
    from esfake.pipeline.redaction import build_redactor

    config_dir = ModelSettings().config_dir
    result = run_calibration(
        corpus, lambda: build_redactor(config_dir), lambda: _common.local_embedder().embed
    )
    if result is None:
        typer.secho(
            "ERROR: calibration needs the `eval` and `index` splits: assign the corpus first "
            "(`esfake corpus assign`, EF-07).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    typer.echo(f"Similarity grid on `eval` ({result.scams} scams, {result.legit} legitimate):")
    typer.echo(f"  {'k':>3} {'delta':>6} {'scams decided':>14} {'legit raised':>13}")
    for point in result.grid:
        typer.echo(
            f"  {point.k:>3} {point.delta:>6.2f} {point.scams_decided:>14} {point.legit_raised:>13}"
        )
    if result.choice is None:
        typer.echo(
            "Every pair raises a legitimate case: keep the provisional values and review the index."
        )
        return
    typer.echo(
        f"Recommended: k = {result.choice.k}, delta = {result.choice.delta:.2f} "
        f"({result.choice.scams_decided} of {result.scams} scams decided, no legitimate raised). "
        "Record them as similarity.k and similarity.delta in config/thresholds.yaml and set "
        "calibrated: true."
    )


def register(app: typer.Typer) -> None:
    similarity_app = typer.Typer(no_args_is_help=True, help="Similarity layer: calibrate k, delta.")
    similarity_app.command("calibrate")(similarity_calibrate)
    app.add_typer(similarity_app, name="similarity")
