"""Deterministic redaction for Peruvian formats (ADR-0004 §1).

Every item becomes a typed placeholder, so the rules still see that, for instance, a phone
number was there. The floor for these types is 100 % on the canary set (ADR-0004 §2).
"""

import re
from collections import Counter

PLACEHOLDERS = {
    "email": "[EMAIL]",
    "card": "[CARD]",
    "account": "[ACCOUNT]",
    "phone": "[PHONE]",
    "dni": "[DNI]",
    "url_query": "[QUERY]",
    "yape_holder": "[NAME]",
}

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+|\b[a-z0-9-]+\.me/[^\s<>\"']+", re.IGNORECASE)
_URL_HOST = re.compile(r"((?:https?://)?[^/?#]+)(.*)", re.DOTALL)

# Digits with the separators people use when writing numbers: spaces, hyphens, parentheses.
# Commas and dots are left out on purpose, so amounts such as "S/ 1,500.00" are never touched.
_DIGIT_RUN = re.compile(r"(?<![\w@])\+?\(?\d[\d \-()]*\d(?![\w@])")
_DNI_WITH_CHECK_DIGIT = re.compile(r"\d{8}-\d")
_LIMA_LANDLINE = re.compile(r"\d{3}[ -]\d{4}")

# A person's name as Yape and bank transfers write it: capitalised words, an optional
# "de / de la / del" particle, initials such as "P.". A word never runs into "/", so the
# currency in "S/ 50" is not taken for an initial.
_NAME_WORD = r"[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü']*\.?(?![/\w])"
_NAME = rf"{_NAME_WORD}(?:\s+(?:(?:de|del|de la|de los)\s+)?{_NAME_WORD}){{0,4}}"
# Only the trigger phrase ignores case; the name itself must be capitalised.
_YAPE_HOLDER = re.compile(
    r"(\b(?i:a nombre de|titular(?: de la cuenta)?:?|beneficiario:?|te yape[oó]|"
    rf"yap[eé]ale a|yapea(?:me|le)? a)\s+)({_NAME})"
)


def _luhn_valid(digits: str) -> bool:
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def classify_number(run: str) -> str | None:
    """Return the redaction type of a run of digits, or None when it is not personal data."""
    digits = re.sub(r"\D", "", run)
    count = len(digits)
    international = run.startswith("+") or digits.startswith("00")
    if _DNI_WITH_CHECK_DIGIT.fullmatch(run):
        return "dni"
    if 13 <= count <= 19 and _luhn_valid(digits):
        return "card"
    if count == 9 and digits.startswith("9"):
        return "phone"  # Peruvian mobile
    if digits.startswith(("519", "00519")) and count in (11, 13):
        return "phone"  # mobile with the country code
    if international and 8 <= count <= 15:
        return "phone"
    if digits.startswith("0") and count in (8, 9):
        return "phone"  # landline with its area code, e.g. (01) 234 5678
    if _LIMA_LANDLINE.fullmatch(run):
        return "phone"
    if count >= 10:
        return "account"  # bank accounts, 20-digit CCI and any other long identifier
    if count == 8:
        return "dni"
    return None


def _redact_numbers(text: str, counts: Counter[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        kind = classify_number(match.group())
        if kind is None:
            return match.group()
        counts[kind] += 1
        return PLACEHOLDERS[kind]

    return _DIGIT_RUN.sub(replace, text)


def _redact_url(url: str, counts: Counter[str]) -> str:
    # The host stays: URL analysis needs it and it is not personal data. Query strings and
    # fragments often carry a victim's identifiers, and paths can hold a phone (wa.me/51...).
    match = _URL_HOST.fullmatch(url)
    host, rest = (match.group(1), match.group(2)) if match else ("", url)
    query = re.search(r"[?#]", rest)
    path = rest if query is None else rest[: query.start()]
    redacted = host + _redact_numbers(path, counts)
    if query is not None:
        counts["url_query"] += 1
        redacted += query.group() + PLACEHOLDERS["url_query"]
    return redacted


def redact_deterministic(text: str) -> tuple[str, Counter[str]]:
    counts: Counter[str] = Counter()

    def replace_email(_match: re.Match[str]) -> str:
        counts["email"] += 1
        return PLACEHOLDERS["email"]

    text = _EMAIL.sub(replace_email, text)

    pieces: list[str] = []
    position = 0
    for match in _URL.finditer(text):
        pieces.append(_redact_numbers(text[position : match.start()], counts))
        pieces.append(_redact_url(match.group(), counts))
        position = match.end()
    pieces.append(_redact_numbers(text[position:], counts))
    text = "".join(pieces)

    def replace_holder(match: re.Match[str]) -> str:
        counts["yape_holder"] += 1
        return match.group(1) + PLACEHOLDERS["yape_holder"]

    return _YAPE_HOLDER.sub(replace_holder, text), counts
