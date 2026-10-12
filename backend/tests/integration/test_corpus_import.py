"""`esfake corpus import` against real Postgres (EF-07): mirror, frozen splits, donations, audit.

Each test runs inside a transaction that is rolled back, so other tests never see its rows,
except the CLI test, which commits through the command and cleans up after itself.
"""

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from typer.testing import CliRunner

import esfake.cli.main
from esfake.cli.main import app
from esfake.corpus.dataset import CorpusRecord, DatasetInfo, write_corpus, write_dataset_info
from esfake.corpus.importer import FrozenCorpusError, ImportReport, import_corpus
from esfake.shared.db.models import (
    AuditLog,
    ChannelIdentity,
    CorpusMessage,
    PipelineManifest,
    Verification,
)
from tests.fakes import FakeEmbedder
from tests.integration.conftest import Database

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
INFO = DatasetInfo(dataset_version="1.0", cluster_threshold=0.9, embedding_model=MODEL)
ACTOR = "import-test"


def record(n: int, split: str = "index", modality: str = "fake_prize") -> CorpusRecord:
    return CorpusRecord.model_validate(
        {
            "case_id": f"t1:{n:064x}",
            "cluster_id": f"cl_import_{n}",
            "source": "public_alert",
            "label": "scam",
            "modality": modality,
            "text": f"Ganaste el premio número {n}, deposita a [ACCOUNT]",
            "added_at": date(2026, 10, 8),
            "split": split,
            "split_assigned_at": date(2026, 10, 9),
        }
    )


def embed(texts: list[str]) -> list[list[float]]:
    return FakeEmbedder().embed(texts)


@pytest.fixture
async def conn(app_engine: AsyncEngine, seeded_modalities: None) -> AsyncIterator[AsyncConnection]:
    async with app_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


async def stored(conn: AsyncConnection) -> dict[str, tuple[str, str, str | None]]:
    rows = await conn.execute(
        select(
            CorpusMessage.case_id,
            CorpusMessage.cluster_id,
            CorpusMessage.split,
            CorpusMessage.modality_code,
        ).where(CorpusMessage.source != "donated")
    )
    return {row.case_id: (row.cluster_id, row.split, row.modality_code) for row in rows}


async def audit(conn: AsyncConnection) -> list[tuple[str, str, list[str]]]:
    rows = await conn.execute(
        select(AuditLog.action, AuditLog.entity_id, AuditLog.changed_fields)
        .where(AuditLog.actor == ACTOR)
        .order_by(AuditLog.id)
    )
    return [(row.action, row.entity_id, row.changed_fields) for row in rows]


async def run(conn: AsyncConnection, records: Sequence[CorpusRecord]) -> ImportReport:
    return await import_corpus(conn, records, INFO, embed, actor=ACTOR, now=NOW)


async def test_import_mirrors_the_jsonl_and_a_reimport_changes_nothing(
    conn: AsyncConnection,
) -> None:
    records = [record(1), record(2, "eval"), record(3, "test")]

    first = await run(conn, records)
    second = await run(conn, records)

    assert first == ImportReport(inserted=3, updated=0, deleted=0, unchanged=0)
    assert second == ImportReport(inserted=0, updated=0, deleted=0, unchanged=3)
    assert await stored(conn) == {
        r.case_id: (r.cluster_id, r.split, r.modality) for r in records if r.case_id
    }
    assert [action for action, _, _ in await audit(conn)] == ["corpus.insert"] * 3


async def test_corrections_are_applied_and_removed_messages_are_deleted(
    conn: AsyncConnection,
) -> None:
    await run(conn, [record(1), record(2), record(3)])
    relabelled = record(1, modality="family_emergency")

    report = await run(conn, [relabelled, record(2)])

    assert report == ImportReport(inserted=0, updated=1, deleted=1, unchanged=1)
    assert (await stored(conn))[str(relabelled.case_id)][2] == "family_emergency"
    assert (await audit(conn))[3:] == [
        ("corpus.update", relabelled.case_id, ["modality_code"]),
        ("corpus.delete", record(3).case_id, []),
    ]


async def test_a_frozen_split_never_moves(conn: AsyncConnection) -> None:
    await run(conn, [record(1, "index")])

    with pytest.raises(FrozenCorpusError, match="never move"):
        await run(conn, [record(1, "test")])
    assert (await stored(conn))[str(record(1).case_id)][1] == "index"


async def test_donations_are_never_touched(conn: AsyncConnection) -> None:
    verification_id = uuid.UUID("01900000-0000-7000-8000-0000000000aa")
    identity_id = uuid.UUID("01900000-0000-7000-8000-0000000000ab")
    await conn.execute(
        insert(PipelineManifest).values(
            manifest_hash="f" * 64,
            git_sha="0" * 40,
            embedding_model=MODEL,
            redactor_version="2",
            thresholds_version="0.4",
            index_snapshot="s",
            created_at=NOW,
        )
    )
    await conn.execute(
        insert(ChannelIdentity).values(
            id=identity_id,
            channel="whatsapp",
            external_id_hmac="t1:" + "a" * 64,
            privacy_notice_accepted_at=NOW,
            created_at=NOW,
        )
    )
    await conn.execute(
        insert(Verification).values(
            id=verification_id,
            identity_id=identity_id,
            channel="whatsapp",
            external_message_hmac="t1:" + "b" * 64,
            received_at=NOW,
            text_redacted="Mamá, deposítame a [ACCOUNT]",
            text_hmac="t1:" + "c" * 64,
            redaction_counts={"ACCOUNT": 1},
            status="done",
            manifest_hash="f" * 64,
            privacy_notice_version="2026-10",
            donated_at=NOW,
            consent_version="2026-10",
            donation_code_hash="t1:" + "d" * 64,
        )
    )
    await conn.execute(
        insert(CorpusMessage).values(
            case_id=str(verification_id),
            source="donated",
            source_verification_id=verification_id,
            text_redacted="Mamá, deposítame a [ACCOUNT]",
            label="scam",
            modality_code="family_emergency",
            language="es",
            cluster_id="cl_donated",
            split="index",
            split_assigned_at=NOW,
            embedding=[0.0] * 384,
            embedding_model=MODEL,
            dataset_version="1.0",
            retain_until=NOW,
            added_by="labeler",
            added_at=NOW,
        )
    )

    report = await run(conn, [record(1)])

    assert report.deleted == 0
    donated = await conn.scalar(
        select(CorpusMessage.case_id).where(CorpusMessage.source == "donated")
    )
    assert donated == str(verification_id)


async def test_the_audit_log_never_holds_message_text(conn: AsyncConnection) -> None:
    records = [record(1), record(2)]
    await run(conn, records)
    await run(conn, [record(1, modality="family_emergency")])

    logged = " ".join(f"{a} {e} {f}" for a, e, f in await audit(conn))

    assert all(r.text not in logged for r in records)
    assert "Ganaste" not in logged


def test_the_cli_imports_with_the_runtime_role(
    database: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = tmp_path / "corpus.jsonl"
    write_corpus(corpus, [record(7), record(8, "eval")])
    write_dataset_info(corpus, INFO)
    monkeypatch.setenv("DATABASE_URL", database.app_url)
    monkeypatch.setenv("ESFAKE_ACTOR", ACTOR)
    monkeypatch.delenv("ESFAKE_INTERNAL_URL", raising=False)
    monkeypatch.setattr(esfake.cli.main, "_local_embedder", FakeEmbedder)
    runner = CliRunner()

    try:
        first = runner.invoke(app, ["corpus", "import", "--corpus", str(corpus)])
        again = runner.invoke(app, ["corpus", "import", "--corpus", str(corpus)])
    finally:
        import asyncio

        asyncio.run(_remove(database, [record(7).case_id, record(8).case_id]))

    assert first.exit_code == 0, first.output
    assert "2 inserted, 0 corrected, 0 deleted, 0 unchanged" in first.stdout
    assert "0 inserted, 0 corrected, 0 deleted, 2 unchanged" in again.stdout


async def _remove(database: Database, case_ids: list[str | None]) -> None:
    from esfake.shared.db import create_engine

    engine = create_engine(database.owner_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                delete(CorpusMessage).where(CorpusMessage.case_id.in_(case_ids))
            )
    finally:
        await engine.dispose()
