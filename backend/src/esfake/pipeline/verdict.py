"""Closed values of a verdict (docs/SPEC.md, `verdicts` table; CLAUDE.md rule 1)."""

from typing import Literal

type Level = Literal["likely_scam", "suspicious", "no_signals"]
type Route = Literal["early_exit", "gray_zone", "risk_trait", "out_of_distribution", "no_route"]
