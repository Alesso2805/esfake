import pickle

import pytest

from esfake.pipeline.normalize import normalize
from esfake.pipeline.text import RawText


def _normalized(text: str) -> str:
    return normalize(RawText(text)).reveal()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("\uff22\uff23\uff30\u3000te informa", "BCP te informa"),  # full-width letters and space
        pytest.param(
            "Llama al \u2079\u2078\u2077 \u2076\u2075\u2074 \u00b3\u00b2\u00b9",
            "Llama al 987 654 321",
            id="superscript digits",
        ),
        pytest.param(
            "Llama al \U0001d7d7\U0001d7d6\U0001d7d5\U0001d7d4"
            "\U0001d7d3\U0001d7d2\U0001d7d1\U0001d7d0\U0001d7cf",
            "Llama al 987654321",
            id="mathematical bold digits",
        ),
        ("98\u200b76\u200c54\u200d321", "987654321"),  # zero-width characters
        ("ver\u00adificación", "verificación"),  # soft hyphen
        ("pago \u202eetnegru\u202c", "pago etnegru"),  # right-to-left override
        ("\ufeffHola", "Hola"),  # byte-order mark
    ],
)
def test_folds_lookalike_characters_and_drops_invisible_ones(given: str, expected: str) -> None:
    assert _normalized(given) == expected


@pytest.mark.parametrize(
    "given",
    [
        "Reenviado\nMamá, cambié de número",
        "Reenviado muchas veces\nMamá, cambié de número",
        "Forwarded\nMamá, cambié de número",
        "[6/10/26, 14:32] Rosa Quispe: Mamá, cambié de número",
        "[06/10/2026, 2:32:10 p. m.] Rosa Quispe: Mamá, cambié de número",
        "6/10/26 14:32 - Rosa Quispe: Mamá, cambié de número",
        "6/10/26, 2:32\u202fp.\u202fm. - Rosa Quispe: Mamá, cambié de número",
    ],
)
def test_drops_forwarding_metadata_including_sender_names(given: str) -> None:
    assert _normalized(given) == "Mamá, cambié de número"


def test_normalises_line_endings_and_blank_runs() -> None:
    assert _normalized("Hola  \r\n\r\n\r\n\r\nYapea ya\r\n") == "Hola\n\nYapea ya"


def test_raw_text_never_shows_or_serialises_its_content() -> None:
    raw = RawText("Mi DNI es 45678912")

    assert "45678912" not in repr(raw)
    assert "45678912" not in str(raw)
    assert "45678912" not in f"{raw}"
    with pytest.raises(TypeError, match="cannot be serialised"):
        pickle.dumps(raw)
