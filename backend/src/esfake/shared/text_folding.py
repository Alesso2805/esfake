"""Case and accent folding that keeps every character in place.

The single `fold` of the code base: rules are written against folded text (lowercase, no
accents), and name redaction matches exempt brands on it, so both must fold identically
(docs/ARCHITECTURE_RULES.md, rule 3). The folded string has the same length as the input, which
lets a match be reported as offsets into the text the user sent.
"""

import unicodedata


def fold(text: str) -> str:
    return "".join(_fold_char(char) for char in text)


def _fold_char(char: str) -> str:
    base = "".join(c for c in unicodedata.normalize("NFD", char) if not unicodedata.combining(c))
    folded = base.lower()
    # A character that would change length stays as it is, so offsets never drift.
    return folded if len(folded) == 1 else char
