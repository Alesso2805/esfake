"""Canary test (EF-06, ADR-0004 §2): personal data never reaches storage, logs or the LLM.

Messages full of invented personal data go through the real intake (normalisation, deterministic
redaction, spaCy names), are stored as the runtime role, logged, and turned into judge payloads.
Then a pg_dump of the database, the captured logs and the payloads are searched for every canary
in every written form.
"""

import io
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from esfake.pipeline.intake import Intake, save_verification
from esfake.pipeline.llm.payload import judge_payload
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.redaction.names import SpacyNameFinder
from esfake.pipeline.text import RawText
from esfake.shared.brands import exempt_terms
from esfake.shared.db.models import PipelineManifest
from esfake.shared.hmac_keys import KeyRing
from esfake.shared.logging import configure_logging
from esfake.shared.models_config import load_models_config
from tests.integration.conftest import Database
from tests.paths import CONFIG_DIR

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
MANIFEST_HASH = "e" * 64

MESSAGES = [
    "Hola mamá, soy Rosaura Quispe Mamani, cambié de número. Deposítame al 987 654 321 "
    "o a la cuenta 191-12345678-0-12.",
    "Te escribe Wilber Huamán Ccori del BCP. Confirma tu DNI 45678912 y tu tarjeta "
    "4111 1111 1111 1111.",
    "Mi correo es rosaura.quispe@gmail.com, mándame el código. CCI 002-191-012345678012-34.",
    "Yapea a Edwin Apaza al +51 912 345 678, es urgente.",
]
CANARIES = [
    # every written form of each number, plus its bare digits
    "987 654 321", "987654321",
    "191-12345678-0-12", "19112345678012",
    "45678912",
    "4111 1111 1111 1111", "4111111111111111",
    "rosaura.quispe@gmail.com",
    "002-191-012345678012-34", "00219101234567801234",
    "+51 912 345 678", "912345678",
    # names
    "Rosaura", "Quispe", "Mamani", "Wilber", "Huamán", "Ccori", "Edwin", "Apaza",
]  # fmt: skip


@pytest.fixture(scope="module")
def intake() -> Intake:
    spacy_model = load_models_config(CONFIG_DIR).spacy.name
    assert spacy_model is not None
    redactor = Redactor(SpacyNameFinder(spacy_model, exempt_terms(CONFIG_DIR)))
    return Intake(redactor, KeyRing.parse("k1:canary-test-hmac-key-0001"))


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    root = logging.getLogger()
    previous = root.handlers[:], root.level
    configure_logging()
    stream = io.StringIO()
    handler = root.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    handler.setStream(stream)
    yield stream
    root.handlers, root.level = previous[0], previous[1]


async def test_canaries_never_reach_the_database_logs_or_llm_payload(
    database: Database, app_engine: AsyncEngine, intake: Intake, captured_logs: io.StringIO
) -> None:
    payloads = []
    async with app_engine.begin() as conn:
        await conn.execute(
            insert(PipelineManifest).values(
                manifest_hash=MANIFEST_HASH,
                git_sha="0" * 40,
                embedding_model="paraphrase-multilingual-MiniLM-L12-v2",
                redactor_version="1",
                thresholds_version="0.1",
                index_snapshot="empty",
                created_at=NOW,
            )
        )
        for message in MESSAGES:
            prepared = intake.prepare(RawText(message))
            payloads.append(json.dumps(judge_payload(prepared.text), ensure_ascii=False))
            await save_verification(
                conn,
                prepared,
                channel="web",
                received_at=NOW,
                manifest_hash=MANIFEST_HASH,
                privacy_notice_version="2026-10",
            )

    surfaces = {
        "database dump": database.dump(),
        "logs": captured_logs.getvalue(),
        "llm payload": "\n".join(payloads),
    }
    for surface, content in surfaces.items():
        leaked = [canary for canary in CANARIES if canary in content]
        assert leaked == [], f"{surface} leaks {leaked}"

    # Guards the guard: the redacted text was really stored and logged.
    assert "[PHONE]" in surfaces["database dump"]
    assert "[NAME]" in surfaces["database dump"]
    assert "message_redacted" in surfaces["logs"]
