"""Models loaded once per process and shared by both listeners."""

import asyncio
from collections.abc import Callable

import structlog

from esfake.pipeline.similarity.embedder import Embedder

log = structlog.get_logger(__name__)


class ModelState:
    def __init__(self) -> None:
        self.embedder: Embedder | None = None

    @property
    def ready(self) -> bool:
        return self.embedder is not None

    async def load(self, factory: Callable[[], Embedder]) -> None:
        """Load off the event loop so liveness keeps answering while the model loads.

        A failure leaves the state not ready: readiness stays 503 and the container is unhealthy.
        """
        try:
            embedder = await asyncio.to_thread(factory)
        except Exception:
            log.exception("model_load_failed")
            return
        self.embedder = embedder
        log.info("model_loaded", model=embedder.model_name, dimensions=embedder.dimensions)
