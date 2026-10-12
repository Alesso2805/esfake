import pytest

from esfake.shared.text_folding import fold


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("Huamán Ñaupari", "huaman naupari"),
        ("CÓDIGO de Ñandú", "codigo de nandu"),
        ("ÁÉÍÓÚ üñ", "aeiou un"),
        ("Banco de Crédito", "banco de credito"),
    ],
)
def test_fold_lowercases_and_strips_accents(text: str, folded: str) -> None:
    assert fold(text) == folded


@pytest.mark.parametrize(
    "text", ["Huamán Ñaupari", "CÓDIGO", "İstanbul", "ﬁnal", "Straße", "日本語"]
)
def test_fold_keeps_every_offset(text: str) -> None:
    assert len(fold(text)) == len(text)
