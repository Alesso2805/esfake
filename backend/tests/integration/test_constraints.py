"""Every CHECK, UNIQUE and trigger rule rejects what it should, as the runtime role (EF-03).

Each case inserts its prerequisites and one offending row inside a transaction that is always
rolled back, and asserts which constraint fired, so a case cannot pass for the wrong reason.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from esfake.shared.db.base import Base
from esfake.shared.db.models import (
    ChannelIdentity,
    Feedback,
    Modality,
    PipelineManifest,
    Signal,
    Url,
    Verdict,
    Verification,
    VerificationQueue,
)

type Row = tuple[type[Base], dict[str, Any]]

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
HMAC = "k1:" + "a" * 64
MANIFEST_HASH = "c" * 64
IDENTITY_ID = uuid.UUID("01900000-0000-7000-8000-000000000001")
VERIFICATION_ID = uuid.UUID("01900000-0000-7000-8000-000000000002")
LLM_CALL = {
    "llm_used": True,
    "route": "gray_zone",
    "llm_model": "claude-haiku-4-5",
    "prompt_version": "judge-v1",
    "input_tokens": 800,
    "output_tokens": 100,
    "cost_usd": Decimal("0.0013"),
}


def manifest(**overrides: Any) -> Row:
    return PipelineManifest, {
        "manifest_hash": MANIFEST_HASH,
        "git_sha": "0" * 40,
        "embedding_model": "paraphrase-multilingual-MiniLM-L12-v2",
        "redactor_version": "r1",
        "thresholds_version": "t1",
        "index_snapshot": "s1",
        "created_at": NOW,
    } | overrides


def modality(**overrides: Any) -> Row:
    return Modality, {
        "code": "test_modality",
        "kind": "textual",
        "name_es": "Prueba",
        "name_en": "Test",
        "is_active": True,
    } | overrides


def identity(**overrides: Any) -> Row:
    return ChannelIdentity, {
        "id": IDENTITY_ID,
        "channel": "whatsapp",
        "external_id_hmac": HMAC,
        "privacy_notice_accepted_at": NOW,
        "created_at": NOW,
    } | overrides


def verification(**overrides: Any) -> Row:
    return Verification, {
        "id": VERIFICATION_ID,
        "identity_id": IDENTITY_ID,
        "channel": "whatsapp",
        "external_message_hmac": HMAC,
        "received_at": NOW,
        "text_redacted": "Hola, soy tu hijo, deposítame a [ACCOUNT]",
        "text_hmac": HMAC,
        "redaction_counts": {"ACCOUNT": 1},
        "status": "pending",
        "manifest_hash": MANIFEST_HASH,
        "privacy_notice_version": "2026-10",
    } | overrides


def queue(**overrides: Any) -> Row:
    return VerificationQueue, {
        "verification_id": VERIFICATION_ID,
        "reply_address_enc": b"ciphertext",
        "enqueued_at": NOW,
        "available_at": NOW,
        "attempts": 0,
    } | overrides


def url(**overrides: Any) -> Row:
    return Url, {
        "verification_id": VERIFICATION_ID,
        "url_redacted": "hxxps://bcp-validacion[.]com",
        "registered_domain": "bcp-validacion.com",
        "is_shortener": False,
        "is_idn": False,
    } | overrides


def signal(**overrides: Any) -> Row:
    return Signal, {
        "verification_id": VERIFICATION_ID,
        "layer": "rules",
        "code": "urgent_money_request",
        "weight": 2.0,
        "modality_code": "family_emergency",
        "evidence_spans": [[0, 4]],
        "neighbor_ids": [],
    } | overrides


def verdict(**overrides: Any) -> Row:
    return Verdict, {
        "verification_id": VERIFICATION_ID,
        "level": "suspicious",
        "score": 0.5,
        "template_ids": ["suspicious.generic"],
        "route": "early_exit",
        "llm_used": False,
        "degraded": False,
        "decided_at": NOW,
    } | overrides


def feedback(**overrides: Any) -> Row:
    return Feedback, {
        "verification_id": VERIFICATION_ID,
        "helpful": True,
        "created_at": NOW,
    } | overrides


VERIFIED = [manifest(), identity(), verification()]

CASES: list[tuple[str, list[Row], Row, str]] = [
    ("modality kind", [], modality(kind="audio"), "ck_modalities_kind_valid"),
    ("modality code", [], modality(code="Fake-Prize"), "ck_modalities_code_format"),
    (
        "manifest hash",
        [],
        manifest(manifest_hash="abc"),
        "ck_pipeline_manifests_manifest_hash_format",
    ),
    ("identity channel", [], identity(channel="sms"), "ck_channel_identities_channel_valid"),
    (
        "identity stores a raw phone number",
        [],
        identity(external_id_hmac="+51987654321"),
        "ck_channel_identities_external_id_hmac_format",
    ),
    (
        "identity duplicate",
        [identity()],
        identity(id=uuid.uuid7()),
        "uq_channel_identities_channel_external_id_hmac",
    ),
    (
        "verification before the privacy notice",
        [manifest(), identity(privacy_notice_accepted_at=None)],
        verification(),
        "has not accepted the privacy notice",
    ),
    (
        "whatsapp verification without identity",
        [manifest()],
        verification(identity_id=None),
        "ck_verifications_identity_required",
    ),
    (
        "whatsapp verification without message id",
        [manifest(), identity()],
        verification(external_message_hmac=None),
        "ck_verifications_external_message_required",
    ),
    (
        "verification status",
        [manifest(), identity()],
        verification(status="queued"),
        "ck_verifications_status_valid",
    ),
    (
        "verification stores raw text as its hmac",
        [manifest(), identity()],
        verification(text_hmac="hola"),
        "ck_verifications_text_hmac_format",
    ),
    (
        "purged verification keeps its text",
        [manifest(), identity()],
        verification(text_purged_at=NOW),
        "ck_verifications_purged_text_empty",
    ),
    (
        "donation without consent",
        [manifest(), identity()],
        verification(donated_at=NOW),
        "ck_verifications_donation_consent",
    ),
    (
        "negative latency",
        [manifest(), identity()],
        verification(latency_ms=-1),
        "ck_verifications_latency_ms_non_negative",
    ),
    (
        "duplicate message",
        VERIFIED,
        verification(id=uuid.uuid7()),
        "uq_verifications_channel_external_message_hmac",
    ),
    ("sixth delivery attempt", VERIFIED, queue(attempts=6), "ck_verification_queue_attempts_range"),
    (
        "queue row both sent and failed",
        VERIFIED,
        queue(sent_at=NOW, failed_at=NOW),
        "ck_verification_queue_sent_or_failed",
    ),
    ("second queue row", [*VERIFIED, queue()], queue(), "uq_verification_queue_verification_id"),
    ("lookalike without score", VERIFIED, url(lookalike_of="bcp.com.pe"), "ck_urls_lookalike_pair"),
    (
        "lookalike score above one",
        VERIFIED,
        url(lookalike_of="bcp.com.pe", lookalike_score=1.5),
        "ck_urls_lookalike_score_range",
    ),
    ("signal layer", VERIFIED, signal(layer="ocr"), "ck_signals_layer_valid"),
    (
        "neighbors outside the similarity layer",
        VERIFIED,
        signal(neighbor_ids=[uuid.uuid7()]),
        "ck_signals_neighbors_from_similarity",
    ),
    ("verdict level", VERIFIED, verdict(level="safe"), "ck_verdicts_level_valid"),
    ("verdict route", VERIFIED, verdict(route="shortcut"), "ck_verdicts_route_valid"),
    (
        "likely_scam without modality",
        VERIFIED,
        verdict(level="likely_scam"),
        "ck_verdicts_likely_scam_modality",
    ),
    (
        "llm used without its fields",
        VERIFIED,
        verdict(llm_used=True, route="gray_zone"),
        "ck_verdicts_llm_fields",
    ),
    (
        "llm fields without llm use",
        VERIFIED,
        verdict(llm_model="claude-haiku-4-5"),
        "ck_verdicts_llm_fields",
    ),
    (
        "llm called on an early exit",
        VERIFIED,
        verdict(**LLM_CALL | {"route": "early_exit"}),
        "ck_verdicts_llm_route",
    ),
    (
        "negative token count",
        VERIFIED,
        verdict(**LLM_CALL | {"input_tokens": -1}),
        "ck_verdicts_usage_non_negative",
    ),
    ("empty feedback", VERIFIED, feedback(helpful=None), "ck_feedback_not_empty"),
    ("feedback label", VERIFIED, feedback(user_label="maybe"), "ck_feedback_user_label_valid"),
    (
        "second feedback",
        [*VERIFIED, feedback()],
        feedback(id=uuid.uuid7()),
        "uq_feedback_verification_id",
    ),
]


async def _insert(engine: AsyncEngine, rows: list[Row], offending: Row | None = None) -> None:
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            for model, values in rows:
                await conn.execute(insert(model).values(**values))
            if offending is not None:
                model, values = offending
                await conn.execute(insert(model).values(**values))
        finally:
            await transaction.rollback()


@pytest.mark.usefixtures("seeded_modalities")
async def test_valid_rows_are_accepted(app_engine: AsyncEngine) -> None:
    web = verification(id=uuid.uuid7(), channel="web", identity_id=None, external_message_hmac=None)
    await _insert(
        app_engine,
        [
            *VERIFIED,
            web,
            queue(),
            url(lookalike_of="bcp.com.pe", lookalike_score=0.92),
            signal(),
            signal(layer="similarity", neighbor_ids=[uuid.uuid7()]),
            verdict(**LLM_CALL | {"level": "likely_scam", "modality_code": "family_emergency"}),
            feedback(user_label="scam"),
        ],
    )


@pytest.mark.usefixtures("seeded_modalities")
@pytest.mark.parametrize(
    ("prerequisites", "offending", "violation"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
async def test_schema_rejects(
    app_engine: AsyncEngine, prerequisites: list[Row], offending: Row, violation: str
) -> None:
    with pytest.raises(IntegrityError, match=violation):
        await _insert(app_engine, prerequisites, offending)
