"""URL analysis without network requests (ADR-0005, EF-12): domains, extraction, shorteners."""

import ast
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

import esfake.pipeline.urls
from esfake.pipeline.text import RedactedText
from esfake.pipeline.urls.analysis import analyze_urls
from esfake.pipeline.urls.config import UrlData, load_url_data
from esfake.pipeline.urls.detector import UrlDetector
from esfake.pipeline.urls.extract import find_urls
from esfake.pipeline.urls.suffixes import PublicSuffixList, load_public_suffix_list
from tests.paths import CONFIG_DIR


@pytest.fixture(scope="module")
def data() -> UrlData:
    return load_url_data(CONFIG_DIR)


@pytest.fixture(scope="module")
def suffixes(data: UrlData) -> PublicSuffixList:
    return data.suffixes


def redacted(text: str) -> RedactedText:
    # Built by hand only in tests: these strings carry no personal data to redact.
    return RedactedText(text)


@pytest.mark.parametrize(
    ("host", "registered"),
    [
        ("www.bcp.com.pe", "bcp.com.pe"),
        ("sunat.gob.pe", "sunat.gob.pe"),
        ("pagos.portal.gob.pe", "portal.gob.pe"),
        ("bcp-validacion.com", "bcp-validacion.com"),
        ("evil.github.io", "evil.github.io"),  # private section: the attacker owns it
        ("com.pe", None),  # a public suffix owns nothing
    ],
)
def test_registered_domains_follow_the_vendored_list(
    suffixes: PublicSuffixList, host: str, registered: str | None
) -> None:
    assert suffixes.registered_domain(host) == registered


def test_wildcard_and_exception_rules(tmp_path: Path) -> None:
    path = tmp_path / "psl.dat"
    path.write_text("// VERSION: test\n*.ck\n!www.ck\npe\ncom.pe\n", encoding="utf-8")
    psl = load_public_suffix_list(path)

    assert psl.registered_domain("shop.foo.ck") == "shop.foo.ck"  # "*.ck": foo.ck is a suffix
    assert psl.registered_domain("www.ck") == "www.ck"  # "!www.ck" overrides the wildcard
    assert psl.registered_domain("a.b.com.pe") == "b.com.pe"
    assert psl.version == "test"


def test_a_snapshot_without_a_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "psl.dat"
    path.write_text("com\n", encoding="utf-8")

    with pytest.raises(ValueError, match="VERSION"):
        load_public_suffix_list(path)


def test_the_vendored_snapshot_is_dated(suffixes: PublicSuffixList) -> None:
    assert suffixes.version.startswith("2026-")


QUERY_URL = "https://bcp-validacion.com/pago?[QUERY]"
USERINFO_URL = "https://www.bcp.com.pe@bcp-validacion.com/x"


@pytest.mark.parametrize(
    ("text", "urls", "hosts"),
    [
        (f"Entra a {QUERY_URL} ya", [QUERY_URL], ["bcp-validacion.com"]),
        ("Ingresa a bit.ly/abc.", ["bit.ly/abc"], ["bit.ly"]),
        ("WWW.BCP.COM.PE/login", ["WWW.BCP.COM.PE/login"], ["www.bcp.com.pe"]),
        ("(ver sunat.gob.pe)", ["sunat.gob.pe"], ["sunat.gob.pe"]),
        # The host is what follows "@"; what comes before is decoration for the victim.
        (USERINFO_URL, [USERINFO_URL], ["bcp-validacion.com"]),
        ("tienda en xn--yap-dma.com", ["xn--yap-dma.com"], ["yapé.com"]),
        ("Paga S/.500 o 1.000 soles, mamá.Llámame hoy", [], []),
    ],
)
def test_urls_are_found_with_and_without_a_scheme(
    suffixes: PublicSuffixList, text: str, urls: list[str], hosts: list[str]
) -> None:
    found = find_urls(text, suffixes)

    assert [f.url for f in found] == urls
    assert [f.host for f in found] == hosts
    assert all(text[f.start : f.end] == f.url for f in found)


def test_punycode_labels_are_decoded_and_flagged(suffixes: PublicSuffixList) -> None:
    [found] = find_urls("xn--yap-dma.com/premio", suffixes)

    assert (found.host, found.punycode) == ("yapé.com", True)


def test_shorteners_are_flagged_by_registered_domain(data: UrlData) -> None:
    findings = analyze_urls(redacted("Mira bit.ly/premio y bitlyy.com/premio"), data)

    assert [(f.registered_domain, f.is_shortener) for f in findings] == [
        ("bit.ly", True),
        ("bitlyy.com", False),
    ]


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("URL analysis tried to use the network")

    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname"):
        monkeypatch.setattr(socket, name, refuse)
    load_url_data.cache_clear()
    load_public_suffix_list.cache_clear()
    yield
    load_url_data.cache_clear()
    load_public_suffix_list.cache_clear()


@pytest.mark.usefixtures("no_network")
def test_url_analysis_opens_no_socket() -> None:
    # ADR-0005 §1: loading the data and analysing every kind of URL stays offline.
    data = load_url_data(CONFIG_DIR)
    text = (
        "https://bcp-validacion.com/pago?[QUERY] bit.ly/abc tinyurl.com/x "
        "xn--yap-dma.com www.bcp.com.pe evil.github.io"
    )

    assert len(analyze_urls(redacted(text), data)) == 6
    assert UrlDetector(data).detect(redacted(text))


def test_the_url_package_imports_nothing_that_reaches_the_network() -> None:
    forbidden = {"socket", "ssl", "http", "urllib.request", "requests", "httpx", "aiohttp"}
    package = Path(esfake.pipeline.urls.__file__).parent
    imported = set()
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

    assert {
        name for name in imported if name in forbidden or name.split(".")[0] in forbidden
    } == set()
