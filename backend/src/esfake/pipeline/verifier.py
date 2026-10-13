"""The pipeline behind one interface, so the API, the worker and the evaluation run the same code.

Detection layers arrive one story at a time (rules and injection in EF-11, URLs in EF-12,
similarity in EF-13, the judge in EF-14).
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from esfake.pipeline.decision.policy_v0 import decide
from esfake.pipeline.llm.cache import ResponseCache
from esfake.pipeline.rules.detector import RuleDetector
from esfake.pipeline.text import RedactedText
from esfake.pipeline.urls.detector import UrlDetector
from esfake.pipeline.verdict import Signal, Verdict
from esfake.shared.thresholds import PolicyV0Thresholds, load_thresholds


class Verifier(Protocol):
    async def verify(self, message: RedactedText) -> Verdict: ...


class Detector(Protocol):
    def detect(self, message: RedactedText) -> Sequence[Signal]: ...


class Pipeline:
    def __init__(self, detectors: Sequence[Detector], policy: PolicyV0Thresholds) -> None:
        self._detectors = tuple(detectors)
        self._policy = policy

    async def verify(self, message: RedactedText) -> Verdict:
        signals = [signal for detector in self._detectors for signal in detector.detect(message)]
        return decide(signals, self._policy)


def build_pipeline(config_dir: Path, judge_cache: ResponseCache) -> Pipeline:
    """The pipeline of this commit: rules and injection (EF-11), then URLs (EF-12). The judge
    (EF-14) will answer through `judge_cache`; nothing reads it yet."""
    return Pipeline(
        [RuleDetector.from_config(config_dir), UrlDetector.from_config(config_dir)],
        load_thresholds(config_dir).policy_v0,
    )
