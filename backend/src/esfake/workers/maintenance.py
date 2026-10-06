"""Maintenance worker (docs/SPEC.md, Arquitectura).

It runs its jobs at every interval with the time of the injected Clock. The jobs themselves
(purging texts after 30 days, deleting reply addresses and sent or failed queue rows after 24 h,
expiring donations, purging rate-limit windows, closing caps) arrive with their stories.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

import structlog

from esfake.shared.clock import Clock

INTERVAL_SECONDS = 60.0

log = structlog.get_logger(__name__)

type Job = Callable[[datetime], Awaitable[None]]


class MaintenanceWorker:
    def __init__(
        self, clock: Clock, jobs: Sequence[Job], *, interval: float = INTERVAL_SECONDS
    ) -> None:
        self._clock = clock
        self._jobs = jobs
        self._interval = interval

    async def run(self, stop: asyncio.Event) -> None:
        log.info("maintenance_worker_started", jobs=len(self._jobs))
        while not stop.is_set():
            now = self._clock.now()
            for job in self._jobs:
                try:
                    await job(now)
                except Exception:
                    # One failing job must not starve the others; the error is logged and the
                    # job runs again on the next pass.
                    log.exception("maintenance_job_failed", job=getattr(job, "__name__", "job"))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
