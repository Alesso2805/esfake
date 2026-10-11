"""Metrics of one evaluation run (EF-08; docs/SPEC.md, Métricas de éxito).

Positive means `likely_scam` or `suspicious`. A false positive is a legitimate message with any
level other than `no_signals`. Strict recall counts only `likely_scam`.
"""

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Self, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from esfake.corpus.dataset import Label
from esfake.evaluation.stats import percentile, wilson_interval
from esfake.pipeline.verdict import Level, Route

LEVELS: tuple[Level, ...] = get_args(Level.__value__)
ROUTES: tuple[Route, ...] = get_args(Route.__value__)
LABELS: tuple[Label, ...] = get_args(Label.__value__)


class CasePrediction(BaseModel):
    """What the evaluated system decided for one case, next to the expected label."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    label: Label
    modality: str | None = None
    subcategory: str | None = None
    level: Level
    route: Route
    llm_used: bool = False
    live_call: bool = False
    latency_ms: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal(0), ge=0)

    @model_validator(mode="after")
    def _expected_fields(self) -> Self:
        if self.label == "scam" and self.modality is None:
            raise ValueError("a scam case needs its modality")
        if self.label == "legit" and self.subcategory is None:
            raise ValueError("a legitimate case needs its subcategory")
        if self.live_call and not self.llm_used:
            raise ValueError("a live call implies the model was used")
        return self

    @property
    def flagged(self) -> bool:
        return self.level != "no_signals"


class Proportion(BaseModel):
    """A proportion with its Wilson 95 % interval; `value` is None when there are no cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int
    total: int
    value: float | None
    low: float
    high: float

    @classmethod
    def of(cls, count: int, total: int) -> Self:
        low, high = wilson_interval(count, total)
        return cls(
            count=count, total=total, value=count / total if total else None, low=low, high=high
        )


class ScamCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cases: int
    detected: int
    likely_scam: int


class LegitCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cases: int
    false_positives: int


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cases: int
    matrix: dict[Level, dict[Label, int]]
    recall: Proportion
    strict_recall: Proportion
    false_positive_rate: Proportion
    by_modality: dict[str, ScamCounts]
    by_subcategory: dict[str, LegitCounts]
    routes: dict[Route, int]
    llm_used: Proportion
    cost_usd_total: Decimal
    cost_usd_mean: Decimal | None
    latency_ms_p50: float | None
    latency_ms_p95: float | None


def compute_metrics(predictions: Sequence[CasePrediction]) -> Metrics:
    scams = [p for p in predictions if p.label == "scam"]
    legit = [p for p in predictions if p.label == "legit"]
    pairs = Counter((p.level, p.label) for p in predictions)
    routes = Counter(p.route for p in predictions)
    modalities = sorted({p.modality for p in scams if p.modality is not None})
    subcategories = sorted({p.subcategory for p in legit if p.subcategory is not None})
    cost = sum((p.cost_usd for p in predictions), Decimal(0))
    latencies = [float(p.latency_ms) for p in predictions]
    return Metrics(
        cases=len(predictions),
        matrix={level: {label: pairs[level, label] for label in LABELS} for level in LEVELS},
        recall=Proportion.of(sum(p.flagged for p in scams), len(scams)),
        strict_recall=Proportion.of(sum(p.level == "likely_scam" for p in scams), len(scams)),
        false_positive_rate=Proportion.of(sum(p.flagged for p in legit), len(legit)),
        by_modality={
            code: ScamCounts(
                cases=sum(p.modality == code for p in scams),
                detected=sum(p.modality == code and p.flagged for p in scams),
                likely_scam=sum(p.modality == code and p.level == "likely_scam" for p in scams),
            )
            for code in modalities
        },
        by_subcategory={
            code: LegitCounts(
                cases=sum(p.subcategory == code for p in legit),
                false_positives=sum(p.subcategory == code and p.flagged for p in legit),
            )
            for code in subcategories
        },
        routes={route: routes[route] for route in ROUTES},
        llm_used=Proportion.of(sum(p.llm_used for p in predictions), len(predictions)),
        cost_usd_total=cost,
        cost_usd_mean=cost / len(predictions) if predictions else None,
        latency_ms_p50=percentile(latencies, 0.50) if latencies else None,
        latency_ms_p95=percentile(latencies, 0.95) if latencies else None,
    )
