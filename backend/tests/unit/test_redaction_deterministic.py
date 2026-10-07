"""Deterministic redaction: 100 % on every canary format (ADR-0004 §2, EF-06).

All values are invented for these tests.
"""

import re

import pytest

from esfake.pipeline.redaction import Redactor
from esfake.pipeline.redaction.deterministic import classify_number, redact_deterministic
from esfake.pipeline.text import RawText


def _redact(text: str) -> str:
    return redact_deterministic(text)[0]


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


CANARIES: list[tuple[str, set[str]]] = [
    # Mobile phones, with and without the country code
    ("987654321", {"[PHONE]"}),
    ("987 654 321", {"[PHONE]"}),
    ("987-654-321", {"[PHONE]"}),
    ("+51 987 654 321", {"[PHONE]"}),
    ("+51987654321", {"[PHONE]"}),
    ("51987654321", {"[PHONE]"}),
    ("0051 987 654 321", {"[PHONE]"}),
    # Landlines and foreign numbers used by scammers
    ("(01) 234-5678", {"[PHONE]"}),
    ("01 2345678", {"[PHONE]"}),
    ("234-5678", {"[PHONE]"}),
    ("(044) 123456", {"[PHONE]"}),
    ("+1 (305) 555-0142", {"[PHONE]"}),
    ("+234 803 123 4567", {"[PHONE]"}),
    # DNI
    ("45678912", {"[DNI]"}),
    ("45678912-3", {"[DNI]"}),
    # Bank accounts and CCI; a Luhn-valid account may come out as a card, still redacted
    ("191-12345678-0-12", {"[ACCOUNT]", "[CARD]"}),
    ("200-3001234567", {"[ACCOUNT]", "[CARD]"}),
    ("0011-0123-0100012345", {"[ACCOUNT]", "[CARD]"}),
    ("002-191-012345678012-34", {"[ACCOUNT]"}),
    # Cards (test numbers that pass Luhn)
    ("4111 1111 1111 1111", {"[CARD]"}),
    ("5500-0000-0000-0004", {"[CARD]"}),
    ("378282246310005", {"[CARD]"}),
    # Emails
    ("rosa.quispe@gmail.com", {"[EMAIL]"}),
    ("pagos+yape@empresa.com.pe", {"[EMAIL]"}),
]


@pytest.mark.parametrize(("canary", "placeholders"), CANARIES, ids=[c for c, _ in CANARIES])
def test_every_canary_format_is_redacted(canary: str, placeholders: set[str]) -> None:
    redacted = _redact(f"Deposita al {canary} hoy mismo, por favor.")

    assert canary not in redacted
    if _digits(canary):
        assert _digits(canary) not in _digits(redacted)
    assert any(placeholder in redacted for placeholder in placeholders)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "Ingresa a https://bcp-validacion.com/login?dni=45678912&cel=987654321 ya",
            "Ingresa a https://bcp-validacion.com/login?[QUERY] ya",
        ),
        ("Escríbeme a wa.me/51987654321", "Escríbeme a wa.me/[PHONE]"),
        ("Mira https://bit.ly/3xYz9Ab", "Mira https://bit.ly/3xYz9Ab"),
        ("Valida en www.yape-premios.net/#ganador=rosa", "Valida en www.yape-premios.net/#[QUERY]"),
    ],
)
def test_urls_keep_their_host_and_lose_identifiers(given: str, expected: str) -> None:
    assert _redact(given) == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("Yapea a Rosa Quispe al 987654321", "Yapea a [NAME] al [PHONE]"),
        ("Te yapeó JUAN P. S/ 50", "Te yapeó [NAME] S/ 50"),
        (
            "Cuenta a nombre de María del Carmen Huamán Ccori",
            "Cuenta a nombre de [NAME]",
        ),
        ("Titular: Luis Alberto Mamani", "Titular: [NAME]"),
    ],
)
def test_yape_and_transfer_holders_are_redacted(given: str, expected: str) -> None:
    assert _redact(given) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Te transfiero S/ 1,500.00 o S/ 50.50",
        "Tu código de verificación es 482913",
        "Vence el 06/10/2026 a las 14:32",
        "Paga 3 cuotas de 150 en el año 2026",
        "Ante cualquier duda llama al 105",
        "El BCP, Interbank, Yape y Plin nunca te piden tu clave",
    ],
)
def test_non_personal_numbers_and_brands_are_left_alone(text: str) -> None:
    assert _redact(text) == text


def test_numbers_that_are_not_personal_data_are_not_classified() -> None:
    assert classify_number("482913") is None
    assert classify_number("2026") is None


def test_redactor_reports_counts_per_type() -> None:
    redacted = Redactor().redact(
        RawText("Soy Rosa, DNI 45678912, llámame al 987654321 o escribe a rosa@gmail.com")
    )

    assert redacted.value == "Soy Rosa, DNI [DNI], llámame al [PHONE] o escribe a [EMAIL]"
    assert redacted.counts == {"dni": 1, "phone": 1, "email": 1}
