"""The pipeline behind one interface, so the API, the worker and the evaluation run the same code.

Detection layers arrive one story at a time (rules and injection in EF-11, URLs in EF-12,
similarity in EF-13, the judge in EF-14); version 0 has none, so policy v0 sees no signals.
"""

from collections.abc import Sequence
from typing import Protocol

from esfake.pipeline.decision.policy_v0 import decide
from esfake.pipeline.text import RedactedText
from esfake.pipeline.verdict import Signal, Verdict
from esfake.shared.thresholds import PolicyV0Thresholds


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
