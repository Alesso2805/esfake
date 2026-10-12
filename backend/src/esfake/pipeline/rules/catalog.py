"""The rule catalogue from config/rules.yaml, validated at load time (CLAUDE.md rule 1).

Patterns are regular expressions over folded text (see `fold`), so they are ASCII and lowercase.
Every rule carries examples that its own test replays: a rule without a positive and a negative
example does not load.
"""

import re
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from esfake.corpus.modalities import load_catalog
from esfake.pipeline.rules.fold import fold

type RuleLayer = Literal["rules", "injection"]


class RuleExamples(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    match: tuple[str, ...] = Field(min_length=1)
    no_match: tuple[str, ...] = Field(min_length=1)


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    layer: RuleLayer
    weight: float = Field(gt=0)
    modality: str | None = None
    patterns: tuple[str, ...] = Field(min_length=1)
    examples: RuleExamples

    @field_validator("patterns")
    @classmethod
    def _folded_and_valid(cls, patterns: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in patterns:
            if not pattern.isascii():
                raise ValueError(f"pattern must be ASCII, written against folded text: {pattern!r}")
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(f"invalid pattern {pattern!r}: {error}") from None
        return patterns

    @model_validator(mode="after")
    def _injection_has_no_modality(self) -> Self:
        if self.layer == "injection" and self.modality is not None:
            raise ValueError(f"{self.code}: an injection rule names no modality")
        return self

    def compiled(self) -> tuple[re.Pattern[str], ...]:
        return tuple(re.compile(p, re.IGNORECASE | re.MULTILINE) for p in self.patterns)

    def spans(self, text: str) -> tuple[tuple[int, int], ...]:
        """Offsets of every match in `text`, folded here, merged where they overlap."""
        folded = fold(text)
        found = sorted(
            (m.start(), m.end())
            for pattern in self.compiled()
            for m in pattern.finditer(folded)
            if m.end() > m.start()
        )
        merged: list[tuple[int, int]] = []
        for start, end in found:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return tuple(merged)


class RuleCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rules: tuple[Rule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_codes(self) -> Self:
        codes = [rule.code for rule in self.rules]
        duplicated = sorted({c for c in codes if codes.count(c) > 1})
        if duplicated:
            raise ValueError(f"duplicate rule codes: {duplicated}")
        return self


def load_rules(config_dir: Path) -> RuleCatalog:
    catalog = RuleCatalog.model_validate(
        yaml.safe_load((config_dir / "rules.yaml").read_text(encoding="utf-8"))
    )
    textual = {
        m.code
        for m in load_catalog(config_dir / "modalities.yaml").modalities
        if m.kind == "textual"
    }
    for rule in catalog.rules:
        if rule.modality is not None and rule.modality not in textual:
            raise ValueError(f"{rule.code}: {rule.modality!r} is not a textual modality")
    return catalog
