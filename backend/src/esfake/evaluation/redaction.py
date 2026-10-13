"""Name-redaction recall and precision on evals/redaction/names.jsonl (ADR-0004 §2).

A gold name counts as redacted only when none of its words survive, so a half-redacted
"Rosa Quispe [NAME]" is a miss. Brands must all survive. Precision counts name spans that
cover no gold name: a verb such as "Depositale" taken for a name erases a scam signal.
"""

import json
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from esfake.evaluation.stats import wilson_interval
from esfake.pipeline.redaction import NAME_PLACEHOLDER, Redactor
from esfake.pipeline.redaction.deterministic import redact_deterministic
from esfake.pipeline.redaction.names import NameFinder, Span
from esfake.pipeline.text import RawText
from esfake.shared.text_folding import fold

_PARTICLES = {"de", "del", "la", "los", "y"}


@dataclass(frozen=True)
class NameCase:
    id: str
    text: str
    names: tuple[str, ...]
    brands: tuple[str, ...]


@dataclass(frozen=True)
class NameRedactionReport:
    cases: int
    names: int
    names_redacted: int
    recall: float
    recall_lower_95: float
    brands: int
    brands_kept: int
    name_spans: int
    name_spans_false: int
    precision: float
    cases_without_names: int
    false_positive_cases: int
    latency_ms_p50: float
    latency_ms_p95: float


def load_cases(path: Path) -> list[NameCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            cases.append(
                NameCase(
                    record["id"], record["text"], tuple(record["names"]), tuple(record["brands"])
                )
            )
    return cases


def _words(name: str) -> list[str]:
    return [w for w in re.findall(r"[^\W\d_]{2,}", fold(name)) if w not in _PARTICLES]


def _survives(word: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(word)}\b", text) is not None


def _gold_spans(text: str, names: tuple[str, ...]) -> list[Span]:
    return [m.span() for name in names for m in re.finditer(re.escape(name), text)]


def _overlaps(span: Span, others: list[Span]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in others)


def evaluate(finder: NameFinder, cases: list[NameCase]) -> NameRedactionReport:
    redactor = Redactor(finder)
    names = redacted_names = brands = kept = negatives = false_positive_cases = 0
    spans = false_spans = 0
    latencies: list[float] = []
    for case in cases:
        started = time.perf_counter()
        output = redactor.redact(RawText(case.text)).value
        latencies.append((time.perf_counter() - started) * 1000)
        folded = fold(output)
        for name in case.names:
            names += 1
            redacted_names += not any(_survives(word, folded) for word in _words(name))
        for brand in case.brands:
            brands += 1
            kept += brand in output
        deterministic, _counts = redact_deterministic(case.text, redactor.suffixes)
        gold = _gold_spans(deterministic, case.names)
        for span in finder.find(deterministic):
            spans += 1
            false_spans += not _overlaps(span, gold)
        if not case.names:
            negatives += 1
            false_positive_cases += NAME_PLACEHOLDER in output
    recall = redacted_names / names if names else 1.0
    quantiles = statistics.quantiles(latencies, n=20) if len(latencies) > 1 else latencies * 19
    return NameRedactionReport(
        cases=len(cases),
        names=names,
        names_redacted=redacted_names,
        recall=recall,
        recall_lower_95=wilson_interval(redacted_names, names)[0],
        brands=brands,
        brands_kept=kept,
        name_spans=spans,
        name_spans_false=false_spans,
        precision=1 - false_spans / spans if spans else 1.0,
        cases_without_names=negatives,
        false_positive_cases=false_positive_cases,
        latency_ms_p50=statistics.median(latencies) if latencies else 0.0,
        latency_ms_p95=quantiles[18] if latencies else 0.0,
    )
