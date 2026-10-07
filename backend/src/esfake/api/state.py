"""Models loaded once per process and shared by both listeners."""

import asyncio
from collections.abc import Callable

import structlog

from esfake.pipeline.redaction import Redactor
from esfake.pipeline.similarity.embedder import Embedder

log = structlog.get_logger(__name__)


class ModelState:
    def __init__(self) -> None:
        self.embedder: Embedder | None = None
        self.redactor: Redactor | None = None

    @property
    def ready(self) -> bool:
        return self.embedder is not None and self.redactor is not None

    async def load(
        self, embedder: Callable[[], Embedder], redactor: Callable[[], Redactor]
    ) -> None:
        """Load off the event loop so liveness keeps answering while the models load.

        A failure leaves the state not ready: readiness stays 503 and the container is unhealthy.
        """
        try:
            loaded_embedder, loaded_redactor = await asyncio.gather(
                asyncio.to_thread(embedder), asyncio.to_thread(redactor)
            )
        except Exception:
            log.exception("model_load_failed")
            return
        self.embedder, self.redactor = loaded_embedder, loaded_redactor
        log.info(
            "models_loaded",
            embedding_model=loaded_embedder.model_name,
            dimensions=loaded_embedder.dimensions,
        )
