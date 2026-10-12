import json
import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

import esfake.cli.main
import esfake.evaluation.embedding_comparison
from esfake.cli.main import app
from esfake.corpus.dataset import CorpusRecord, write_corpus
from esfake.corpus.pairs import ReviewPair, record_ref, write_pairs
from esfake.evaluation.embedding_comparison import (
    ModelMeasures,
    auc_difference,
    compare,
    roc_auc,
)

LABELS = [False, False, True, True]


def test_auc_is_the_chance_a_same_pair_outranks_a_different_one() -> None:
    assert roc_auc([0.1, 0.2, 0.8, 0.9], LABELS) == 1.0
    assert roc_auc([0.9, 0.8, 0.2, 0.1], LABELS) == 0.0
    assert roc_auc([0.1, 0.4, 0.35, 0.8], LABELS) == 0.75
    assert roc_auc([0.5, 0.5, 0.5, 0.5], LABELS) == 0.5  # ties count half
    with pytest.raises(ValueError, match="both"):
        roc_auc([0.1, 0.2], [True, True])


def test_the_paired_interval_is_reproducible_and_brackets_the_gain() -> None:
    labels = [False, True] * 20
    deployed = [0.5 + (0.2 if same else 0.0) + (i % 7) * 0.04 for i, same in enumerate(labels)]
    contender = [0.5 + (0.4 if same else 0.0) + (i % 7) * 0.01 for i, same in enumerate(labels)]

    first = auc_difference(contender, deployed, labels, resamples=500)
    again = auc_difference(contender, deployed, labels, resamples=500)
    same = auc_difference(deployed, deployed, labels, resamples=200)

    assert first == again
    assert first.low <= first.difference <= first.high
    assert first.difference > 0
    assert (same.difference, same.low, same.high) == (0.0, 0.0, 0.0)


def measures(name: str, scores: list[float], latency: float) -> ModelMeasures:
    return ModelMeasures(
        name=name,
        scores=scores,
        latencies_ms=[latency] * 10,
        token_counts=[20, 40, 130, 600],
        max_tokens=128,
    )


@pytest.mark.parametrize(
    ("contender_scores", "latency", "switch", "reason"),
    [
        ([0.1, 0.2, 0.8, 0.9] * 10, 20.0, True, "above 0 at 95 %"),
        ([0.1, 0.2, 0.8, 0.9] * 10, 250.0, False, "exceeds the 200 ms budget"),
        ([0.2, 0.3, 0.25, 0.4] * 10, 20.0, False, "not above 0"),
    ],
)
def test_the_contender_switches_only_with_a_clear_gain_within_budget(
    contender_scores: list[float], latency: float, switch: bool, reason: str
) -> None:
    deployed = measures("minilm", [0.2, 0.3, 0.25, 0.4] * 10, 10.0)

    result = compare(
        deployed,
        measures("e5", contender_scores, latency),
        LABELS * 10,
        date(2026, 10, 11),
        resamples=300,
    )

    assert result.switch is switch
    assert any(reason in r for r in result.reasons)
    assert result.deployed.share_over == {128: 0.5, 512: 0.25}


class TopicEmbedder:
    """'tema 3' maps to axis 3; the contender also tells near-duplicates ('bis') apart less."""

    def __init__(self, contender: bool = False) -> None:
        self.contender = contender
        self.model_name = "e5-fake" if contender else "minilm-fake"
        self.max_tokens = 512 if contender else 128

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            topic = int(re.search(r"tema (\d+)", text)[1])  # type: ignore[index]
            vector = [0.0] * 32
            vector[topic] = 1.0
            if "bis" in text and not self.contender:
                vector[31] = 0.9  # the deployed fake blurs variants; the contender does not
            vectors.append(vector)
        return vectors

    def token_counts(self, texts: Sequence[str]) -> list[int]:
        return [len(text.split()) for text in texts]


def test_the_command_writes_the_evidence_and_the_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = [
        CorpusRecord(
            source="public_alert",
            label="scam",
            modality="fake_prize",
            text=text,
            added_at=date(2026, 10, 8),
        )
        for text in ("Ganaste, tema 1", "Ganaste, tema 1 bis", "Tu pedido, tema 2", "Hola, tema 3")
    ]
    corpus, pairs_csv, out = tmp_path / "c.jsonl", tmp_path / "p.csv", tmp_path / "e.json"
    write_corpus(corpus, records)
    refs = [record_ref(r) for r in records]
    pairs = [ReviewPair(refs[0], refs[1], "", ""), ReviewPair(refs[0], refs[2], "", "")]
    pairs += [ReviewPair(refs[2], refs[3], "", ""), ReviewPair(refs[1], refs[3], "", "")]
    write_pairs(pairs_csv, pairs)
    labelled = pairs_csv.read_text(encoding="utf-8-sig").splitlines()
    answers = ["si", "no", "no", "no"]
    rows = [labelled[0]] + [
        line.replace(",,", f",{answer},", 1)
        for line, answer in zip(labelled[1:], answers, strict=True)
    ]
    pairs_csv.write_text("\n".join(rows) + "\n", encoding="utf-8-sig")
    monkeypatch.setattr(esfake.cli.main, "_local_embedder", TopicEmbedder)
    # Latency runs each real model in a fresh process; here it is a fixed figure.
    monkeypatch.setattr(
        esfake.evaluation.embedding_comparison,
        "measure_latencies",
        lambda config, cache_dir, texts, *, offline: [5.0] * len(texts),
    )

    result = CliRunner().invoke(
        app,
        ["corpus", "compare-models", "--pairs", str(pairs_csv), "--corpus", str(corpus),
         "--out", str(out)],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    evidence = json.loads(out.read_text(encoding="utf-8"))
    assert evidence["pairs"] == 4
    assert evidence["same"] == 1
    assert evidence["deployed"]["name"] == "minilm-fake"
    assert evidence["contender"]["max_tokens"] == 512
    assert "Decision:" in result.stdout
