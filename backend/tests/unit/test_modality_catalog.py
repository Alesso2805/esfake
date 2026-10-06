from collections import Counter

import pytest
from pydantic import ValidationError

from esfake.corpus.modalities import ModalityCatalog, load_catalog
from tests.paths import MODALITIES_YAML

SPEC = {"code": "fake_prize", "kind": "textual", "name_es": "Falso premio", "name_en": "Fake prize"}


def test_repository_catalog_lists_seven_textual_and_two_guidance_modalities() -> None:
    catalog = load_catalog(MODALITIES_YAML)

    assert Counter(modality.kind for modality in catalog.modalities) == {
        "textual": 7,
        "guidance_only": 2,
    }


def test_duplicate_codes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        ModalityCatalog.model_validate({"modalities": [SPEC, SPEC]})


@pytest.mark.parametrize(
    "override",
    [{"kind": "audio"}, {"code": "Fake-Prize"}, {"name_en": ""}, {"extra": "field"}],
)
def test_invalid_entries_are_rejected(override: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ModalityCatalog.model_validate({"modalities": [SPEC | override]})
