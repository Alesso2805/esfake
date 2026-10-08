"""Name redaction with the real spaCy model from config/models.yaml (ADR-0004 §2).

The recall floor is checked on the validation set only; it was never used for tuning.
"""

from pathlib import Path

import pytest

from esfake.evaluation.redaction import evaluate, load_cases
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.redaction.names import SpacyNameFinder
from esfake.pipeline.text import RawText
from esfake.shared.brands import exempt_terms
from esfake.shared.models_config import load_models_config
from esfake.shared.thresholds import load_thresholds
from tests.paths import CONFIG_DIR, NAMES_DEV, NAMES_VALIDATION


@pytest.fixture(scope="module")
def finder() -> SpacyNameFinder:
    model = load_models_config(CONFIG_DIR).spacy.name
    assert model is not None
    return SpacyNameFinder(model, exempt_terms(CONFIG_DIR))


def test_name_recall_on_validation_meets_the_floor(finder: SpacyNameFinder) -> None:
    report = evaluate(finder, load_cases(NAMES_VALIDATION))

    assert report.recall >= load_thresholds(CONFIG_DIR).redaction.name_recall_floor
    assert report.precision >= load_thresholds(CONFIG_DIR).redaction.name_precision_floor
    assert report.latency_ms_p95 < 150


@pytest.mark.parametrize("dataset", [NAMES_DEV, NAMES_VALIDATION], ids=["dev", "validation"])
def test_every_brand_survives(finder: SpacyNameFinder, dataset: Path) -> None:
    report = evaluate(finder, load_cases(dataset))

    assert report.brands_kept == report.brands


def test_a_brand_next_to_a_name_survives(finder: SpacyNameFinder) -> None:
    redacted = Redactor(finder).redact(RawText("Soy Rosa del BCP, deposita ya")).value

    assert "BCP" in redacted
    assert "Rosa" not in redacted


def test_a_sentence_initial_verb_is_not_taken_for_a_name(finder: SpacyNameFinder) -> None:
    redacted = Redactor(finder).redact(RawText("Deposítale a Juan Quispe hoy mismo")).value

    assert redacted.startswith("Deposítale")
    assert "Juan" not in redacted
    assert "Quispe" not in redacted


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Opening words of the relative-in-trouble scam are its signal, never a name.
        ("Papá estoy en la comisaría, me detuvieron por error", None),
        ("Abuelita soy tu nieto, estoy en problemas", None),
        ("Hola mami, soy yo, me robaron el cel", None),
        ("FELICIDADES, Usted ha sido seleccionado para un trabajo a distancia", None),
        ("Tu pedido de Rappi está en camino", None),
        (
            "Hola tío, soy Valeria, estoy en el hospital",
            "Hola tío, soy [NAME], estoy en el hospital",
        ),
    ],
)
def test_greetings_kinship_and_brands_survive_while_names_do_not(
    finder: SpacyNameFinder, text: str, expected: str | None
) -> None:
    redacted = Redactor(finder).redact(RawText(text)).value

    assert redacted == (expected or text)
