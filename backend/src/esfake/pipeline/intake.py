"""From a received message to stored, redacted text (ADR-0004 §1).

`prepare` is the single entry point that sees raw text: it normalises, redacts and fingerprints
the redacted text. Everything after it, storage and logging included, only takes what it returns.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from esfake.pipeline.normalize import normalize
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.text import RawText, RedactedText
from esfake.shared.db.models import Verification
from esfake.shared.hmac_keys import KeyRing
from esfake.shared.ids import new_id

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PreparedMessage:
    text: RedactedText
    text_hmac: str


class Intake:
    def __init__(self, redactor: Redactor, keys: KeyRing) -> None:
        self._redactor = redactor
        self._keys = keys

    def prepare(self, raw: RawText) -> PreparedMessage:
        redacted = self._redactor.redact(normalize(raw))
        prepared = PreparedMessage(redacted, self._keys.digest(redacted.value))
        # Counts only: never message text, raw or redacted (CLAUDE.md rule 4).
        log.info("message_redacted", redaction_counts=redacted.counts)
        return prepared


async def save_verification(
    conn: AsyncConnection,
    message: PreparedMessage,
    *,
    channel: str,
    received_at: datetime,
    manifest_hash: str,
    privacy_notice_version: str,
    identity_id: uuid.UUID | None = None,
    external_message_hmac: str | None = None,
) -> uuid.UUID:
    verification_id = new_id()
    await conn.execute(
        insert(Verification).values(
            id=verification_id,
            identity_id=identity_id,
            channel=channel,
            external_message_hmac=external_message_hmac,
            received_at=received_at,
            text_redacted=message.text.value,
            text_hmac=message.text_hmac,
            redaction_counts=message.text.counts,
            status="pending",
            manifest_hash=manifest_hash,
            privacy_notice_version=privacy_notice_version,
        )
    )
    log.info("verification_saved", verification_id=str(verification_id), channel=channel)
    return verification_id
