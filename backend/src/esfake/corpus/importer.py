"""`esfake corpus import`: mirror the public corpus JSONL into `corpus_messages` (rule 6, EF-07).

The committed JSONL is the source of truth for public messages, and the import never assigns:
- a new case_id is inserted with its embedding;
- a case_id already stored keeps its source, text, cluster and split, or the import stops,
  because a frozen split never moves; its label, modality, subcategory and language may be
  corrected;
- a public message whose case_id left the JSONL is deleted;
- donations (source `donated`) live only in the database and are never touched.

Every change leaves an `audit_log` row with the case_id and the changed field names, never text.
The caller owns the transaction, so a failed import changes nothing.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from esfake.corpus.dataset import CorpusRecord, DatasetInfo
from esfake.shared.db.models import AuditLog, CorpusMessage

FROZEN = ("source", "text_redacted", "cluster_id", "split")
CORRECTABLE = ("label", "modality_code", "subcategory", "language")


@dataclass(frozen=True)
class ImportReport:
    inserted: int
    updated: int
    deleted: int
    unchanged: int


class FrozenCorpusError(ValueError):
    pass


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _columns(record: CorpusRecord) -> dict[str, object]:
    return {
        "source": record.source,
        "text_redacted": record.text,
        "cluster_id": record.cluster_id,
        "split": record.split,
        "label": record.label,
        "modality_code": record.modality,
        "subcategory": record.subcategory,
        "language": record.language,
    }


async def import_corpus(
    conn: AsyncConnection,
    records: Sequence[CorpusRecord],
    info: DatasetInfo,
    embed: Callable[[list[str]], list[list[float]]],
    *,
    actor: str,
    now: datetime,
) -> ImportReport:
    if any(r.case_id is None or r.cluster_id is None or r.split is None for r in records):
        raise ValueError("every message needs its case_id, cluster and split: run corpus assign")
    rows = await conn.execute(
        select(
            CorpusMessage.case_id, *(getattr(CorpusMessage, c) for c in FROZEN + CORRECTABLE)
        ).where(CorpusMessage.source != "donated")
    )
    stored = {row.case_id: row._mapping for row in rows}

    moved = [
        str(r.case_id)
        for r in records
        if r.case_id in stored and any(stored[r.case_id][c] != _columns(r)[c] for c in FROZEN)
    ]
    if moved:
        raise FrozenCorpusError(
            f"{len(moved)} stored messages changed source, text, cluster or split, which never "
            f"move once assigned: {sorted(moved)[:10]}"
        )

    audit: list[dict[str, object]] = []

    def log(action: str, case_id: str, fields: Sequence[str] = ()) -> None:
        audit.append(
            {
                "actor": actor,
                "action": action,
                "entity_type": "corpus_message",
                "entity_id": case_id,
                "changed_fields": list(fields),
                "at": now,
            }
        )

    new = [r for r in records if r.case_id not in stored]
    vectors = embed([r.text for r in new]) if new else []
    for record, vector in zip(new, vectors, strict=True):
        await conn.execute(
            insert(CorpusMessage).values(
                case_id=record.case_id,
                **_columns(record),
                split_assigned_at=_midnight(record.split_assigned_at or record.added_at),
                embedding=vector,
                embedding_model=info.embedding_model,
                dataset_version=info.dataset_version,
                added_by=actor,
                added_at=_midnight(record.added_at),
            )
        )
        log("corpus.insert", str(record.case_id))

    updated = 0
    for record in records:
        if record.case_id not in stored:
            continue
        changes = {
            c: v for c, v in _columns(record).items()
            if c in CORRECTABLE and stored[record.case_id][c] != v
        }  # fmt: skip
        if changes:
            await conn.execute(
                update(CorpusMessage).where(CorpusMessage.case_id == record.case_id).values(changes)
            )
            log("corpus.update", str(record.case_id), sorted(changes))
            updated += 1

    gone = sorted(set(stored) - {r.case_id for r in records})
    if gone:
        await conn.execute(delete(CorpusMessage).where(CorpusMessage.case_id.in_(gone)))
        for case_id in gone:
            log("corpus.delete", case_id)

    if audit:
        await conn.execute(insert(AuditLog), audit)
    return ImportReport(
        inserted=len(new),
        updated=updated,
        deleted=len(gone),
        unchanged=len(records) - len(new) - updated,
    )
