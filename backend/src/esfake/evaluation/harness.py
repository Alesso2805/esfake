"""Runs the pipeline over the corpus cases of one split (EF-08).

Corpus text is already redacted, but it goes through normalisation and the redactor again, so
the evaluation measures the same path, and the same latency, as a production verification.
"""

import time
from collections.abc import Sequence
from decimal import Decimal

from esfake.corpus.dataset import CorpusRecord, Split
from esfake.evaluation.metrics import CasePrediction
from esfake.pipeline.normalize import normalize
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.text import RawText
from esfake.pipeline.verifier import Verifier


def split_cases(records: Sequence[CorpusRecord], split: Split) -> list[CorpusRecord]:
    """Cases of one split; messages without a case_id have not been assigned yet (EF-07)."""
    return [r for r in records if r.split == split and r.case_id is not None]


async def run_cases(
    cases: Sequence[CorpusRecord], redactor: Redactor, verifier: Verifier
) -> list[CasePrediction]:
    predictions = []
    for case in cases:
        if case.case_id is None:
            raise ValueError("evaluation cases need a case_id")
        start = time.perf_counter()
        verdict = await verifier.verify(redactor.redact(normalize(RawText(case.text))))
        latency_ms = round((time.perf_counter() - start) * 1000)
        predictions.append(
            CasePrediction(
                case_id=case.case_id,
                label=case.label,
                modality=case.modality,
                subcategory=case.subcategory,
                level=verdict.level,
                route=verdict.route,
                llm_used=verdict.llm is not None,
                live_call=verdict.llm is not None and not verdict.llm.cached,
                latency_ms=latency_ms,
                cost_usd=verdict.llm.cost_usd if verdict.llm is not None else Decimal(0),
            )
        )
    return predictions
