"""Evaluation commands: the `eval` gate, `eval-record`, the red-team stub and the redaction report.

`redteam` is a stub until EF-17: it prints a warning and exits 0 so `make redteam` and CI can
call it from Sprint 0 on.
"""

import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from esfake.cli import _common
from esfake.cli._common import DEFAULT_CORPUS
from esfake.shared.config import ModelSettings
from esfake.shared.models_config import load_models_config

if TYPE_CHECKING:
    from esfake.pipeline.llm.cache import CacheMode


def _warn_stub(command: str, story: str) -> None:
    typer.secho(
        f"WARNING: `esfake {command}` is a stub until {story}; nothing was evaluated.",
        fg=typer.colors.YELLOW,
        err=True,
    )


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
    from esfake.evaluation.run import EvaluationRequest, run_evaluation
    from esfake.pipeline.redaction import build_redactor
    from esfake.shared.clock import SystemClock

    config_dir = ModelSettings().config_dir
    request = EvaluationRequest(
        mode, corpus, evals_dir, llm_cache, config_dir, _git_sha(), budget_usd, publish_as
    )
    result = run_evaluation(
        request,
        lambda: build_redactor(config_dir),
        SystemClock(),
        make_embed=lambda: _common.local_embedder().embed,
    )

    if result.status == "no_cases":
        typer.secho(result.error, fg=typer.colors.YELLOW, err=True)
        return
    if result.status == "model_error":
        typer.secho(result.error, fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if result.report is not None:
        typer.echo(result.report)
    if result.note is not None:
        typer.echo(result.note)
    if result.status == "gate_failed":
        raise typer.Exit(1)
    if result.status == "publish_refused":
        typer.secho(result.error, fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    if result.published_path is not None:
        typer.echo(f"Published {publish_as} to {result.published_path}; commit it.")


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


def eval_record(
    corpus: Annotated[Path, typer.Option(help="Corpus JSONL.")] = DEFAULT_CORPUS,
    evals_dir: Annotated[Path, typer.Option(help="Published versions.")] = DEFAULT_EVALS,
    llm_cache: Annotated[Path, typer.Option(help="Recorded model responses.")] = DEFAULT_LLM_CACHE,
    budget: Annotated[float, typer.Option(help="Spending cap in US$.")] = EVAL_RECORD_BUDGET_USD,
) -> None:
    """Record missing model responses within a budget, then run the gate without them."""
    _evaluate("record", corpus, evals_dir, llm_cache, budget_usd=Decimal(str(budget)))


def redteam() -> None:
    """Run the `redteam/dev` attack suite (EF-17)."""
    _warn_stub("redteam", "EF-17")


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


def register(app: typer.Typer) -> None:
    app.command("eval")(eval_)
    app.command("eval-record")(eval_record)
    app.command("redteam")(redteam)
    app.command("redaction-report")(redaction_report)
