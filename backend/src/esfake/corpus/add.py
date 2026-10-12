"""`esfake corpus add`: redact raw messages and append them to the public corpus (EF-07, EF-09).

The raw file must live outside the repository, so unredacted text can never be committed. Rows
are validated before anything is written; an error names the row and the field, never the text.
"""

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from esfake.corpus.dataset import CorpusRecord, Label, Source, read_corpus, write_corpus
from esfake.corpus.subcategories import SubcategoryCatalog
from esfake.pipeline.normalize import normalize
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.text import RawText
from esfake.shared.clock import Clock
from esfake.shared.modalities import ModalityCatalog

COLUMNS = ("text", "label", "modality", "subcategory", "source", "reference", "language")


class RawCorpusRow(BaseModel):
    """One message as collected; `text` is raw and never echoed in errors."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    text: str = Field(min_length=1)
    label: Label
    source: Source
    modality: str | None = None
    subcategory: str | None = None
    reference: str | None = None
    language: str = "es"


class CorpusInputError(ValueError):
    pass


@dataclass
class AddReport:
    added: int = 0
    duplicates: int = 0
    redactions: Counter[str] = field(default_factory=Counter)


def _rows(path: Path) -> list[dict[str, str | None]]:
    text = path.read_text(encoding="utf-8-sig")  # spreadsheets often add a BOM
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(text.splitlines(keepends=True)))
        unknown = set(rows[0]) - set(COLUMNS) if rows else set()
        if unknown:
            raise CorpusInputError(f"unknown columns: {sorted(unknown)}; expected {COLUMNS}")
        return [{key: (value or None) for key, value in row.items()} for row in rows]
    raise CorpusInputError("the raw file must be .csv or .jsonl")


def load_raw_rows(
    path: Path,
    repo_root: Path,
    catalog: ModalityCatalog,
    subcategories: SubcategoryCatalog,
) -> list[RawCorpusRow]:
    if path.resolve().is_relative_to(repo_root.resolve()):
        raise CorpusInputError(
            "raw messages must live outside the repository, so they can never be committed"
        )
    textual = {m.code for m in catalog.modalities if m.kind == "textual"}
    rows: list[RawCorpusRow] = []
    problems: list[str] = []
    for number, data in enumerate(_rows(path), start=1):
        try:
            row = RawCorpusRow.model_validate({k: v for k, v in data.items() if v is not None})
        except ValidationError as error:
            fields = sorted({".".join(map(str, e["loc"])) or "row" for e in error.errors()})
            problems.append(f"row {number}: invalid {', '.join(fields)}")
            continue
        if row.label == "scam" and row.modality not in textual:
            problems.append(f"row {number}: a scam needs one of the textual modalities")
        elif row.modality is not None and row.modality not in textual:
            problems.append(f"row {number}: unknown or non-textual modality")
        elif row.label == "legit" and row.subcategory is None:
            problems.append(f"row {number}: a legitimate message needs a subcategory")
        elif row.label == "legit" and row.subcategory not in subcategories.codes:
            problems.append(f"row {number}: unknown subcategory (config/subcategories.yaml)")
        elif row.label == "scam" and row.subcategory is not None:
            problems.append(f"row {number}: scams carry no subcategory")
        else:
            rows.append(row)
    if problems:
        raise CorpusInputError("; ".join(problems))
    return rows


def add_messages(
    rows: list[RawCorpusRow], corpus_path: Path, redactor: Redactor, clock: Clock
) -> AddReport:
    """Redact every row and append the new ones; exact duplicates (same text and source) skip."""
    records = read_corpus(corpus_path)
    seen = {(record.source, record.text) for record in records}
    report = AddReport()
    today = clock.now().date()
    for row in rows:
        redacted = redactor.redact(normalize(RawText(row.text)))
        report.redactions.update(redacted.counts)
        if (row.source, redacted.value) in seen:
            report.duplicates += 1
            continue
        seen.add((row.source, redacted.value))
        records.append(
            CorpusRecord(
                source=row.source,
                label=row.label,
                modality=row.modality,
                subcategory=row.subcategory,
                language=row.language,
                text=redacted.value,
                reference=row.reference,
                added_at=today,
            )
        )
        report.added += 1
    write_corpus(corpus_path, records)
    return report
