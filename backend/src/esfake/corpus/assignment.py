"""One `esfake corpus assign` run: check the cut and the dataset version, assign, write.

The CLI only turns options into a request and the result into output and exit codes; when
assigning is refused, what is assigned and which dataset version it makes are decided here
(docs/ARCHITECTURE_RULES.md, rule 4). The algorithm itself is `corpus.assign` (CLAUDE.md rule 6).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from esfake.corpus.assign import (
    AssignReport,
    DatasetVersionError,
    assign,
    next_dataset_info,
    unassigned,
)
from esfake.corpus.dataset import (
    DatasetInfo,
    read_corpus,
    read_dataset_info,
    write_corpus,
    write_dataset_info,
)
from esfake.corpus.validate import EXCLUDED_REVIEW_SHARE
from esfake.shared.clock import Clock
from esfake.shared.hmac_keys import KeyRing
from esfake.shared.models_config import load_models_config
from esfake.shared.thresholds import load_thresholds

type Status = Literal["refused", "nothing_new", "assigned"]


@dataclass(frozen=True)
class AssignmentRequest:
    corpus: Path
    config_dir: Path
    new_major: bool = False


@dataclass(frozen=True)
class AssignmentResult:
    """What happened. `error` explains a refusal; the rest is set once messages were assigned."""

    status: Status
    error: str | None = None
    info: DatasetInfo | None = None
    report: AssignReport | None = None
    excluded: int = 0
    total: int = 0

    @property
    def threshold_needs_review(self) -> bool:
        """Over 5 % of the corpus excluded: the cut groups too little (CLAUDE.md rule 6)."""
        return self.total > 0 and self.excluded / self.total > EXCLUDED_REVIEW_SHARE


def run_assignment(
    request: AssignmentRequest,
    keys: Callable[[], KeyRing],
    embed: Callable[[list[str]], list[list[float]]],
    clock: Clock,
) -> AssignmentResult:
    """`keys` and `embed` are called only when there is something to assign.

    `keys` raises ValueError with a message for the person running the command when the corpus
    key ring is missing or malformed.
    """
    cut = load_thresholds(request.config_dir).corpus
    if not cut.cluster_threshold_reviewed:
        return AssignmentResult(
            "refused",
            error="the cluster threshold is still provisional. Review pairs with `esfake corpus "
            "pairs` and `esfake corpus threshold`, record the value in config/thresholds.yaml "
            "and set cluster_threshold_reviewed: true (ADR-0003, section 6).",
        )
    previous = read_dataset_info(request.corpus)
    records = read_corpus(request.corpus)
    if request.new_major:
        records = unassigned(records)
    if all(record.split is not None for record in records):
        return AssignmentResult("nothing_new")
    try:
        key_ring = keys()
        info = next_dataset_info(
            previous,
            threshold=cut.cluster_threshold,
            embedding_model=load_models_config(request.config_dir).embedding.name,
            new_major=request.new_major,
        )
    except (DatasetVersionError, ValueError) as error:
        return AssignmentResult("refused", error=str(error))

    vectors = embed([record.text for record in records])
    try:
        result, report = assign(
            records, vectors, cut.cluster_threshold, key_ring, clock.now().date()
        )
    except ValueError as error:
        return AssignmentResult("refused", error=str(error))
    info = info.model_copy(
        update={"discarded_synthetic": info.discarded_synthetic + report.discarded_synthetic}
    )
    write_corpus(request.corpus, result)
    write_dataset_info(request.corpus, info)
    return AssignmentResult(
        "assigned",
        info=info,
        report=report,
        excluded=sum(record.split == "excluded" for record in result),
        total=len(result),
    )
