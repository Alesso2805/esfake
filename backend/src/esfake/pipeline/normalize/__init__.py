"""Stage 1a: normalisation, before redaction (ADR-0001 §1)."""

import re
import unicodedata

from esfake.pipeline.text import RawText

# Invisible characters used to break up phone numbers or hide text: soft hyphen, zero-width
# characters, directional marks and overrides, invisible operators and the BOM.
_INVISIBLE = re.compile("[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")

# Forwarding metadata that comes along when a message is copied or exported from WhatsApp.
# The copied headers also carry the sender's name, so they go before redaction ever sees them.
_FORWARDED_LABEL = re.compile(
    r"^\s*(?:reenviado(?: muchas veces)?|forwarded(?: many times)?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TIME = r"\d{1,2}:\d{2}(?::\d{2})?(?:\s?[ap]\.?\s?m\.?)?"
_DATE = r"\d{1,2}/\d{1,2}/\d{2,4}"
_COPIED_HEADER = re.compile(
    rf"^(?:\[{_DATE},?\s{_TIME}\]|{_DATE},?\s{_TIME}\s-)\s[^:\n]{{1,60}}:\s",
    re.IGNORECASE | re.MULTILINE,
)
_BLANK_RUNS = re.compile(r"\n{3,}")


def normalize(raw: RawText) -> RawText:
    # NFKC folds full-width, superscript and styled digits and letters into plain ones, so
    # "\uff19\uff18\uff17" or "\U0001d7d7\U0001d7d6\U0001d7d5" reach the redactor as "987".
    text = unicodedata.normalize("NFKC", raw.reveal())
    text = _INVISIBLE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FORWARDED_LABEL.sub("", text)
    text = _COPIED_HEADER.sub("", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _BLANK_RUNS.sub("\n\n", text)
    return RawText(text.strip())
