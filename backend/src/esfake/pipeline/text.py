"""The two kinds of message text (ADR-0004 §1).

`RawText` exists only between receipt and the redactor: it is not a `str`, so type checking
stops it from reaching a repository, a log call or an LLM client, and it never prints its
content. Only the normaliser and the redactor may call `reveal()`, and only the redactor builds
`RedactedText`; tests/unit/test_text_boundary.py enforces both rules.
"""

from dataclasses import dataclass, field
from typing import NoReturn


class RawText:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "RawText(<hidden>)"

    __str__ = __repr__

    def __reduce__(self) -> NoReturn:
        raise TypeError("RawText cannot be serialised")


@dataclass(frozen=True, slots=True)
class RedactedText:
    """Text after redaction, with how many items of each type were replaced."""

    value: str
    counts: dict[str, int] = field(default_factory=dict)
