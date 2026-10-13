"""Brand names in foreign domains, lookalikes and IDN (ADR-0005 §2, EF-12 part b)."""

from collections.abc import Mapping
from pathlib import Path

import pytest

from esfake.pipeline.text import RedactedText
from esfake.pipeline.urls.analysis import UrlFinding, analyze_urls
from esfake.pipeline.urls.config import UrlData, load_url_data
from esfake.pipeline.urls.confusables import load_confusables, shape, skeleton
from esfake.pipeline.urls.lookalike import edit_distance, similarity
from esfake.pipeline.urls.official import official_brands
from esfake.shared.brands import Brand, BrandCatalog
from tests.paths import CONFIG_DIR

CYRILLIC_A, CYRILLIC_ES = chr(0x0430), chr(0x0441)


@pytest.fixture(scope="module")
def data() -> UrlData:
    return load_url_data(CONFIG_DIR)


@pytest.fixture(scope="module")
def confusables(data: UrlData) -> Mapping[str, str]:
    return data.confusables


def test_lookalike_characters_share_a_skeleton(confusables: Mapping[str, str]) -> None:
    assert skeleton("1nterbank", confusables) == skeleton("lnterbank", confusables)
    assert skeleton(f"y{CYRILLIC_A}pe", confusables) == skeleton("yape", confusables)
    assert skeleton("g00gle", confusables) == skeleton("google", confusables)
    assert shape("Yapé", confusables) == shape("yape", confusables)


def test_an_empty_confusables_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "confusables.txt"
    path.write_text("# nothing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no confusables"):
        load_confusables(path)


def test_edit_distance_and_similarity() -> None:
    assert edit_distance("interbank", "lnterbank") == 1
    assert edit_distance("bbva", "bbvaa") == 1
    assert similarity("bbva", "bbvaa") == pytest.approx(0.8)
    assert similarity("", "") == 1.0


def test_brand_names_come_from_the_name_and_official_domains_not_aliases(
    data: UrlData, confusables: Mapping[str, str]
) -> None:
    catalog = BrandCatalog(
        brands=(
            Brand(name="Banco Falabella", aliases=("Falabella",), domains=("bancofalabella.pe",)),
            Brand(name="RENIEC", aliases=("RENIEC",), domains=("gob.pe",)),
            Brand(name="Plin", aliases=("Plin",)),  # no verified domain yet
        )
    )

    falabella, reniec = official_brands(catalog, data.suffixes, confusables)

    assert falabella.names == ("bancofalabella",)
    assert falabella.owner_labels == ("bancofalabella",)
    assert reniec.owner_labels == (None,)  # a public suffix: every domain under it is official
    assert reniec.owns("reniec.gob.pe")


def finding(data: UrlData, text: str) -> UrlFinding:
    [found] = analyze_urls(RedactedText(text), data)
    return found


@pytest.mark.parametrize(
    ("text", "brand", "lookalike_of"),
    [
        ("bcp-validacion.com/pago", "BCP", None),
        ("mibcp24.com", "BCP", None),  # digits and hyphens separate the parts of a label
        (f"b{CYRILLIC_ES}p-pagos.com", "BCP", None),  # a Cyrillic "c" still reads "bcp"
        ("yape-premios.net", "Yape", None),
        ("whatsapp-soporte.com", "WhatsApp", None),
        ("sunat-devoluciones.com", "SUNAT", None),
        ("lnterbank.pe", None, "interbank.pe"),
        ("interbank.com", "Interbank", "interbank.pe"),  # the name under another suffix
        ("rnibanco.com", "Mibanco", "mibanco.com.pe"),  # "rn" reads "m"
        ("xn--yap-dma.com.pe", "Yape", "yape.com.pe"),
    ],
)
def test_fake_domains_name_or_imitate_a_brand(
    data: UrlData, text: str, brand: str | None, lookalike_of: str | None
) -> None:
    found = finding(data, text)

    assert (found.brand_token, found.lookalike_of) == (brand, lookalike_of)


@pytest.mark.parametrize(
    "text",
    [
        "www.viabcp.com/login",  # official
        "scotiabank.com.pe",  # official
        "reniec.gob.pe",  # official: RENIEC owns gob.pe
        "falabella.com",  # a shop, not the bank: aliases are not looked for
        "abcpets.com",  # "bcp" inside a word is not a brand
        "bbvb.pe",  # 0.75 similar to bbva.pe: under the threshold
    ],
)
def test_official_and_unrelated_domains_raise_nothing(data: UrlData, text: str) -> None:
    found = finding(data, text)

    assert (found.brand_token, found.lookalike_of, found.lookalike_score) == (None, None, None)


def test_the_lookalike_threshold_comes_from_thresholds_yaml(data: UrlData) -> None:
    assert data.lookalike_min_similarity == 0.80
    assert finding(data, "bbvaa.pe").lookalike_score == pytest.approx(0.8)


def test_idn_and_mixed_scripts_are_flagged(data: UrlData) -> None:
    accented = finding(data, "xn--yap-dma.com")
    mixed = finding(data, f"b{CYRILLIC_ES}p-pagos.com")
    plain = finding(data, "bcp-validacion.com")

    assert (accented.is_idn, accented.mixed_script) == (True, False)
    assert (mixed.is_idn, mixed.mixed_script) == (True, True)
    assert (plain.is_idn, plain.mixed_script) == (False, False)
