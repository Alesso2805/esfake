"""Closed values of a verdict (docs/SPEC.md, `verdicts` and `signals` tables; CLAUDE.md rule 1)."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type Level = Literal["likely_scam", "suspicious", "no_signals"]
type Route = Literal["early_exit", "gray_zone", "risk_trait", "out_of_distribution", "no_route"]
type Layer = Literal["rules", "injection", "urls", "similarity", "llm"]


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    layer: Layer
    code: str
    weight: float
    modality: str | None = None
    # (start, end) offsets into the redacted text; they feed `signals.evidence_spans`.
    spans: tuple[tuple[int, int], ...] = ()
    # Similarity only: the neighbours behind the signal, which feed `signals.neighbor_ids`
    # (corpus_messages ids in production, case_ids in evaluation).
    neighbor_ids: tuple[str, ...] = ()


class LLMUsage(BaseModel):
    """One call to the judge; `cached` means the response came from the cache, not the model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    prompt_version: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    cached: bool


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: Level
    route: Route
    score: float
    modality: str | None
    signals: tuple[Signal, ...]
    llm: LLMUsage | None = None
    degraded: bool = False
