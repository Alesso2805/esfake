"""One evaluation run: score the `eval` split, apply the gate and optionally publish a version.

The CLI only turns options into a request and the result into output and exit codes; what is
evaluated, what is compared and when a version may be published is decided here
(docs/ARCHITECTURE_RULES.md, rule 4).
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal

from esfake.corpus.dataset import CorpusRecord, read_corpus
from esfake.corpus.subcategories import load_subcategories
from esfake.evaluation.gate import run_gate
from esfake.evaluation.harness import run_cases, split_cases
from esfake.evaluation.metrics import compute_metrics
from esfake.evaluation.published import latest_published, publish
from esfake.evaluation.report import format_report
from esfake.pipeline.llm.cache import (
    BudgetExceededError,
    CacheMode,
    MissingResponseError,
    ResponseCache,
)
from esfake.pipeline.manifest import build_manifest
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.similarity.detector import Embed, SimilarityDetector
from esfake.pipeline.similarity.index import IndexEntry, InMemoryIndex
from esfake.pipeline.verifier import build_pipeline
from esfake.shared.clock import Clock
from esfake.shared.thresholds import load_thresholds

type Status = Literal["no_cases", "model_error", "gate_failed", "publish_refused", "ok"]


@dataclass(frozen=True)
class EvaluationRequest:
    mode: CacheMode
    corpus: Path
    evals_dir: Path
    llm_cache: Path
    config_dir: Path
    git_sha: str
    budget_usd: Decimal | None = None
    publish_as: str | None = None


@dataclass(frozen=True)
class EvaluationResult:
    """What happened, and the text for the person running it.

    `report` is for stdout whenever it is set; `error` is for stderr; `note` is extra stdout after
    the report (what `eval-record` recorded). `published_path` is set only when a version was
    written.
    """

    status: Status
    report: str | None = None
    note: str | None = None
    error: str | None = None
    published_path: Path | None = None


def _similarity(
    records: Sequence[CorpusRecord], make_embed: Callable[[], Embed] | None, config_dir: Path
) -> SimilarityDetector | None:
    """The similarity layer over the `index` split held in memory (ADR-0002 §5), if any."""
    index_records = [r for r in split_cases(records, "index") if r.case_id is not None]
    if make_embed is None or not index_records:
        return None
    embed = make_embed()
    index = InMemoryIndex(
        [IndexEntry(str(r.case_id), r.label, r.modality) for r in index_records],
        embed([r.text for r in index_records]),
    )
    return SimilarityDetector(embed, index, load_thresholds(config_dir).similarity)


def run_evaluation(
    request: EvaluationRequest,
    make_redactor: Callable[[], Redactor],
    clock: Clock,
    make_embed: Callable[[], Embed] | None = None,
) -> EvaluationResult:
    """`make_embed` loads the embedding model, only when the corpus has an `index` split."""
    config_dir = request.config_dir
    records = read_corpus(request.corpus)
    cases = split_cases(records, "eval")
    if not cases:
        return EvaluationResult(
            "no_cases",
            error="WARNING: the corpus has no `eval` cases yet (`esfake corpus assign`, EF-07); "
            "nothing was evaluated.",
        )
    index_ids = [r.case_id for r in split_cases(records, "index") if r.case_id is not None]
    manifest = build_manifest(config_dir, request.git_sha, index_ids)
    cache = ResponseCache(request.llm_cache, request.mode, request.budget_usd)
    pipeline = build_pipeline(config_dir, cache, _similarity(records, make_embed, config_dir))
    try:
        predictions = asyncio.run(run_cases(cases, make_redactor(), pipeline))
    except (MissingResponseError, BudgetExceededError) as error:
        return EvaluationResult("model_error", error=f"ERROR: {error}")

    metrics = compute_metrics(predictions)
    published = latest_published(request.evals_dir)
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
    report = format_report(request.mode, manifest.hash, metrics, gate)
    note = None
    if request.mode == "record":
        note = (
            f"Recorded {cache.live_calls} responses live for US${cache.spent_usd}; "
            f"commit {request.llm_cache} with the PR."
        )
    if not gate.passed:
        return EvaluationResult("gate_failed", report=report, note=note)
    if request.publish_as is None:
        return EvaluationResult("ok", report=report, note=note)

    if manifest.git_sha.endswith("-dirty") or manifest.git_sha == "unknown":
        return EvaluationResult(
            "publish_refused",
            report=report,
            note=note,
            error="ERROR: commit every change before publishing, so the manifest names the code.",
        )
    try:
        path = publish(
            request.evals_dir,
            request.publish_as,
            clock.now().date(),
            manifest,
            metrics,
            predictions,
        )
    except ValueError as error:
        return EvaluationResult(
            "publish_refused", report=report, note=note, error=f"ERROR: {error}"
        )
    return EvaluationResult("ok", report=report, note=note, published_path=path)
