"""Structural test: raw text cannot leak past the redactor (ADR-0004 §1, EF-06).

Only the normaliser and the redactor may read `RawText`, and only the redactor may build
`RedactedText`. Anything else that tried would have to call `reveal()` or `RedactedText(...)`,
and this scan finds every such call in the package.
"""

import ast
from pathlib import Path

import pytest

import esfake

PACKAGE_DIR = Path(esfake.__file__).parent
MAY_REVEAL = ("esfake.pipeline.text", "esfake.pipeline.normalize", "esfake.pipeline.redaction")
MAY_BUILD_REDACTED = ("esfake.pipeline.redaction",)


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _calls(name: str) -> list[tuple[str, int]]:
    found = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            callee = node.func
            called = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
            if called == name:
                found.append((_module_name(path), node.lineno))
    return found


def _outside(calls: list[tuple[str, int]], allowed: tuple[str, ...]) -> list[tuple[str, int]]:
    return [
        (module, line)
        for module, line in calls
        if not any(module == prefix or module.startswith(prefix + ".") for prefix in allowed)
    ]


@pytest.mark.parametrize(
    ("call", "allowed"),
    [("reveal", MAY_REVEAL), ("RedactedText", MAY_BUILD_REDACTED)],
)
def test_raw_text_is_only_handled_inside_normalisation_and_redaction(
    call: str, allowed: tuple[str, ...]
) -> None:
    assert _outside(_calls(call), allowed) == []


def test_the_scan_sees_the_allowed_calls() -> None:
    # Guards the guard: if the scan stopped finding calls, the test above would pass vacuously.
    assert any(module == "esfake.pipeline.normalize" for module, _ in _calls("reveal"))
