"""The URL layer as signals and in the pipeline (ADR-0005, EF-12 part c)."""

import re
import shutil
from pathlib import Path

import pytest

from esfake.pipeline.decision.policy_v0 import decide
from esfake.pipeline.llm.cache import ResponseCache
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.text import RawText, RedactedText
from esfake.pipeline.urls.config import load_url_data
from esfake.pipeline.urls.detector import UrlDetector
from esfake.pipeline.verdict import Verdict
from esfake.pipeline.verifier import build_pipeline
from esfake.shared.thresholds import load_thresholds
from tests.paths import CONFIG_DIR

CYRILLIC_ES = chr(0x0441)


@pytest.fixture(scope="module")
def detector() -> UrlDetector:
    return UrlDetector.from_config(CONFIG_DIR)


def verdict(detector: UrlDetector, text: str) -> Verdict:
    return decide(detector.detect(RedactedText(text)), load_thresholds(CONFIG_DIR).policy_v0)


@pytest.mark.parametrize(
    ("text", "level", "modality"),
    [
        ("Valida tus datos en bcp-validacion.com/pago", "likely_scam", "bank_wallet_phishing"),
        ("Soporte: whatsapp-soporte.com", "likely_scam", "whatsapp_code_theft"),
        ("Tu cuenta en lnterbank.pe", "likely_scam", "bank_wallet_phishing"),
        # No textual modality fits impersonating the state: suspicious, not likely_scam.
        ("Devolución en sunat-devoluciones.com", "suspicious", None),
        (f"Ingresa a b{CYRILLIC_ES}p.net", "likely_scam", "bank_wallet_phishing"),
        # A shortener or an accent alone does not reach suspicious; genuine messages use them.
        ("Promo en bit.ly/abc", "no_signals", None),
        ("Visita xn--caf-dma.com", "no_signals", None),  # café.com: an accent, no brand
        ("Paga en www.viabcp.com", "no_signals", None),
    ],
)
def test_url_signals_through_policy_v0(
    detector: UrlDetector, text: str, level: str, modality: str | None
) -> None:
    result = verdict(detector, text)

    assert (result.level, result.modality) == (level, modality)


def test_one_signal_per_kind_with_every_url_that_raised_it(detector: UrlDetector) -> None:
    text = "Usa bcp-pagos.com o bcp-clientes.com"

    [signal] = detector.detect(RedactedText(text))

    assert (signal.layer, signal.code, signal.weight) == ("urls", "url_brand_unofficial", 3.0)
    assert [text[start:end] for start, end in signal.spans] == ["bcp-pagos.com", "bcp-clientes.com"]


def test_mixed_scripts_alone_reach_suspicious(detector: UrlDetector) -> None:
    text = f"x{CYRILLIC_ES}y-tienda.com"

    codes = [signal.code for signal in detector.detect(RedactedText(text))]

    assert codes == ["url_mixed_script"]
    assert verdict(detector, text).level == "suspicious"


async def test_the_demo_link_that_imitates_a_bank_is_likely_scam_in_the_pipeline(
    tmp_path: Path,
) -> None:
    # docs/SPEC.md, demo scenario 2, through redaction and every layer of this commit.
    pipeline = build_pipeline(CONFIG_DIR, ResponseCache(tmp_path, "cached_strict"))
    message = Redactor().redact(
        RawText("Estimado cliente, actualice sus datos en https://bcp-validacion.com/login?id=77")
    )

    result = await pipeline.verify(message)

    assert (result.level, result.modality) == ("likely_scam", "bank_wallet_phishing")
    assert "url_brand_unofficial" in {signal.code for signal in result.signals}


def _config_with(tmp_path: Path, old: str, new: str) -> Path:
    config = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, config)
    path = config / "urls.yaml"
    text = path.read_text(encoding="utf-8")
    assert re.search(re.escape(old), text)
    path.write_text(text.replace(old, new), encoding="utf-8")
    return config


@pytest.mark.parametrize(
    ("old", "new", "error"),
    [
        ("  WhatsApp: whatsapp_code_theft", "  Nadie: whatsapp_code_theft", "not in official"),
        ("  WhatsApp: whatsapp_code_theft", "  WhatsApp: virtual_kidnapping", "not textual"),
        ("  url_idn: 0.5 ", "  # url_idn: 0.5 ", "no weight"),
    ],
)
def test_the_url_configuration_is_validated(tmp_path: Path, old: str, new: str, error: str) -> None:
    config = _config_with(tmp_path, old, new)

    with pytest.raises(ValueError, match=error):
        load_url_data(config)
