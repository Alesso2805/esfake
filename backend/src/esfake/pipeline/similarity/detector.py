"""Detector for the similarity layer (EF-13; docs/SPEC.md, Similitud).

It decides only when the k nearest `index` messages are all scams and the least similar of them
beats the nearest legitimate message by delta. Then it raises one positive signal with the
neighbours' ids; otherwise it raises nothing. It never lowers a verdict, so similarity alone can
never produce `no_signals` (CLAUDE.md rule 3).
"""

import asyncio
from collections.abc import Callable, Sequence

from esfake.pipeline.similarity.index import Neighbor, SimilarityIndex
from esfake.pipeline.text import RedactedText
from esfake.pipeline.verdict import Signal
from esfake.shared.thresholds import SimilarityThresholds

type Embed = Callable[[list[str]], list[list[float]]]

SIGNAL_CODE = "similar_known_scam"


def decides(nearest: Sequence[Neighbor], legit: Neighbor | None, k: int, delta: float) -> bool:
    """The rule of the layer, shared with calibration: the k nearest are all scams and the least
    similar of them beats the nearest legitimate message by delta. `nearest` may hold more than k,
    most similar first."""
    first = nearest[:k]
    if len(first) < k or any(neighbor.label != "scam" for neighbor in first):
        return False
    return legit is None or min(n.similarity for n in first) >= legit.similarity + delta


class SimilarityDetector:
    def __init__(
        self, embed: Embed, index: SimilarityIndex, thresholds: SimilarityThresholds
    ) -> None:
        self._embed = embed
        self._index = index
        self._thresholds = thresholds

    async def detect(self, message: RedactedText) -> Sequence[Signal]:
        # CPU-bound: off the event loop, so both API listeners keep answering.
        [vector] = await asyncio.to_thread(self._embed, [message.value])
        k, delta = self._thresholds.k, self._thresholds.delta
        nearest = await self._index.nearest(vector, k)
        legit = await self._index.nearest(vector, 1, label="legit")
        if not decides(nearest, legit[0] if legit else None, k, delta):
            return []
        modalities = {neighbor.modality for neighbor in nearest}
        return [
            Signal(
                layer="similarity",
                code=SIGNAL_CODE,
                weight=self._thresholds.weight,
                # The modality the k neighbours share; none if they disagree.
                modality=modalities.pop() if len(modalities) == 1 else None,
                neighbor_ids=tuple(neighbor.id for neighbor in nearest),
            )
        ]
