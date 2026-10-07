from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from esfake.corpus.add import CorpusInputError, add_messages, load_raw_rows
from esfake.corpus.dataset import CorpusRecord, read_corpus
from esfake.corpus.modalities import ModalityCatalog, load_catalog
from esfake.pipeline.redaction import Redactor
from esfake.shared.clock import FakeClock
from tests.paths import MODALITIES_YAML

HEADER = "text,label,modality,subcategory,source,reference,language\n"
SCAM = (
    '"Mamá, soy yo, cambié de número. Yapéame al 987654321",'
    "scam,family_emergency,,public_alert,https://example.pe/alerta,es\n"
)
LEGIT = '"Tu pedido llegó a la portería",legit,,delivery_notice,curated_legit,,es\n'


@pytest.fixture
def catalog() -> ModalityCatalog:
    return load_catalog(MODALITIES_YAML)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _raw(tmp_path: Path, content: str, name: str = "batch.csv") -> Path:
    outside = tmp_path / "outside"
    outside.mkdir(exist_ok=True)
    path = outside / name
    path.write_text(content, encoding="utf-8-sig")  # with the BOM spreadsheets add
    return path


def test_rows_are_read_from_a_spreadsheet_csv(
    tmp_path: Path, repo: Path, catalog: ModalityCatalog
) -> None:
    rows = load_raw_rows(_raw(tmp_path, HEADER + SCAM + LEGIT), repo, catalog)

    assert [(row.label, row.modality, row.subcategory) for row in rows] == [
        ("scam", "family_emergency", None),
        ("legit", None, "delivery_notice"),
    ]


def test_raw_files_inside_the_repository_are_refused(repo: Path, catalog: ModalityCatalog) -> None:
    inside = repo / "batch.csv"
    inside.write_text(HEADER + SCAM, encoding="utf-8")

    with pytest.raises(CorpusInputError, match="outside the repository"):
        load_raw_rows(inside, repo, catalog)


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        ('"Gana un premio",scam,,,public_alert,,es\n', "textual modalities"),
        ('"Te llamo luego",legit,,,curated_legit,,es\n', "needs a subcategory"),
        ('"Comprobante",scam,fake_payment_receipt,,public_alert,,es\n', "textual modalities"),
        ('"Hola",maybe,,easy,curated_legit,,es\n', "invalid label"),
        ('"Hola",legit,,easy,donated,,es\n', "invalid source"),
    ],
)
def test_invalid_rows_are_reported_by_number_without_their_text(
    tmp_path: Path, repo: Path, catalog: ModalityCatalog, row: str, problem: str
) -> None:
    with pytest.raises(CorpusInputError, match=problem) as error:
        load_raw_rows(_raw(tmp_path, HEADER + LEGIT + row), repo, catalog)

    assert "row 2" in str(error.value)
    text = row.split('"')[1]
    assert text not in str(error.value)


def test_messages_are_redacted_before_they_are_written_and_duplicates_skip(
    tmp_path: Path, repo: Path, catalog: ModalityCatalog
) -> None:
    corpus = repo / "evals" / "datasets" / "corpus.jsonl"
    rows = load_raw_rows(_raw(tmp_path, HEADER + SCAM + LEGIT), repo, catalog)
    clock = FakeClock(datetime(2026, 10, 7, 9, 0, tzinfo=UTC))

    first = add_messages(rows, corpus, Redactor(), clock)
    second = add_messages(rows, corpus, Redactor(), clock)

    records = read_corpus(corpus)
    assert (first.added, first.duplicates, second.added, second.duplicates) == (2, 0, 0, 2)
    assert first.redactions == {"phone": 1}
    assert "987654321" not in corpus.read_text(encoding="utf-8")
    assert records[0].text.endswith("Yapéame al [PHONE]")
    assert {r.added_at for r in records} == {date(2026, 10, 7)}
    assert all(r.case_id is None and r.split is None for r in records)


@pytest.mark.parametrize(
    ("fields", "error"),
    [
        ({"label": "scam"}, "needs its modality"),
        ({"label": "legit"}, "needs a subcategory"),
        (
            {"label": "legit", "subcategory": "easy", "source": "synthetic", "split": "test"},
            "never go to test",
        ),
    ],
)
def test_corpus_records_enforce_the_schema_rules(fields: dict[str, str], error: str) -> None:
    base = {"source": "public_alert", "text": "hola", "added_at": "2026-10-07"}

    with pytest.raises(ValueError, match=error):
        CorpusRecord.model_validate(base | fields)
