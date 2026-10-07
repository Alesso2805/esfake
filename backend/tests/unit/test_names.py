from collections.abc import Sequence

import pytest

from esfake.pipeline.redaction import Redactor
from esfake.pipeline.redaction.names import Span, _subtract, cued_name_spans, fold
from esfake.pipeline.text import RawText


def _cued(text: str) -> list[str]:
    return [text[start:end] for start, end in cued_name_spans(text)]


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("Hola mamá, soy Maritza, cambié de número", ["Maritza"]),
        ("¡Felicidades Nilda! Ganaste un premio", ["Nilda"]),
        ("Hola Tía Rosa, ¿cómo estás?", ["Rosa"]),
        ("Le escribe la Lic. Zoila Melgarejo", ["Zoila Melgarejo"]),
        ("Hola Mamá, ya llegué", []),
        ("Gracias Dios por este día", []),
        ("soy yo, tu primo", []),
    ],
)
def test_cue_phrases_find_capitalised_names_but_not_kinship_words(
    text: str, names: list[str]
) -> None:
    assert _cued(text) == names


def test_fold_keeps_offsets_aligned() -> None:
    text = "Huamán Ñaupari"

    assert fold(text) == "huaman naupari"
    assert len(fold(text)) == len(text)


def test_subtract_cuts_holes_out_of_a_span() -> None:
    assert _subtract((0, 20), [(5, 8), (12, 30)]) == [(0, 5), (8, 12)]


class FakeNames:
    def __init__(self, spans: Sequence[Span]) -> None:
        self._spans = list(spans)

    def find(self, text: str) -> list[Span]:
        return self._spans


def test_overlapping_name_spans_become_one_placeholder() -> None:
    redacted = Redactor(FakeNames([(4, 8), (4, 15), (9, 15)])).redact(RawText("Soy Rosa Quispe."))

    assert redacted.value == "Soy [NAME]."
    assert redacted.counts == {"name": 1}
