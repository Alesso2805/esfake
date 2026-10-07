"""The versioned public corpus, evals/datasets/corpus.jsonl (CLAUDE.md rule 6).

Every record holds redacted text only. `esfake corpus add` appends new records without case_id,
cluster or split; `esfake corpus assign` (EF-07, part c) fills those three once and freezes them.
Donations never appear here: they live only in the database.
"""

import json
from datetime import date
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type Source = Literal["public_alert", "curated_legit", "synthetic"]
type Label = Literal["scam", "legit"]
type Split = Literal["index", "eval", "test", "excluded"]


class CorpusRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str | None = None
    source: Source
    label: Label
    modality: str | None = None
    subcategory: str | None = None
    language: str = Field(default="es", min_length=2, max_length=8)
    text: str = Field(min_length=1)
    reference: str | None = None
    added_at: date
    cluster_id: str | None = None
    split: Split | None = None
    split_assigned_at: date | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.label == "scam" and self.modality is None:
            raise ValueError("a scam needs its modality")
        if self.label == "legit" and self.subcategory is None:
            raise ValueError("a legitimate message needs a subcategory ('easy' for easy ones)")
        if self.source == "synthetic" and self.split == "test":
            raise ValueError("synthetic messages never go to test")
        return self


def read_corpus(path: Path) -> list[CorpusRecord]:
    if not path.exists():
        return []
    return [
        CorpusRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_corpus(path: Path, records: list[CorpusRecord]) -> None:
    """One record per line, keys in schema order, UTF-8 and LF, so diffs stay readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record.model_dump(mode="json"), ensure_ascii=False) for record in records]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("".join(line + "\n" for line in lines))
