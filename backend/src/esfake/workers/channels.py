"""Channel worker (ADR-0002 §2, CLAUDE.md rule 7).

It wakes on NOTIFY over a direct connection, never a pooler, with a polling fallback every 5 s,
and hands each wake-up to a handler. Until EF-23 the handler only logs; claiming rows with
`FOR UPDATE SKIP LOCKED`, calling `/internal/verify`, sending and retrying arrive with it.
"""

import asyncio
from collections.abc import Awaitable, Callable

import asyncpg
import structlog
from sqlalchemy.engine import make_url

QUEUE_CHANNEL = "verification_queue"
POLL_INTERVAL_SECONDS = 5.0

log = structlog.get_logger(__name__)

type WakeHandler = Callable[[], Awaitable[None]]


def asyncpg_dsn(sqlalchemy_url: str) -> str:
    """asyncpg takes a plain postgresql:// DSN, not SQLAlchemy's postgresql+asyncpg:// URL."""
    url = make_url(sqlalchemy_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


async def log_wake() -> None:
    log.debug("channel_worker_woke")


class ChannelWorker:
    def __init__(
        self,
        direct_dsn: str,
        on_wake: WakeHandler,
        *,
        poll_interval: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._dsn = direct_dsn
        self._on_wake = on_wake
        self._poll_interval = poll_interval
        self._notified = asyncio.Event()
        self.listening = asyncio.Event()

    async def run(self, stop: asyncio.Event) -> None:
        connection = await self._listen()
        try:
            while not stop.is_set():
                if connection.is_closed():
                    log.warning("channel_worker_reconnecting")
                    connection = await self._listen()
                # Cleared before draining, so a NOTIFY that lands mid-drain triggers another pass.
                self._notified.clear()
                await self._on_wake()
                await self._wait(stop)
        finally:
            await connection.close()

    async def _listen(self) -> asyncpg.Connection:
        connection = await asyncpg.connect(self._dsn)
        await connection.add_listener(QUEUE_CHANNEL, self._on_notification)
        self.listening.set()
        log.info("channel_worker_listening", channel=QUEUE_CHANNEL)
        return connection

    def _on_notification(self, *_args: object) -> None:
        self._notified.set()

    async def _wait(self, stop: asyncio.Event) -> None:
        waiters = [asyncio.create_task(self._notified.wait()), asyncio.create_task(stop.wait())]
        try:
            await asyncio.wait(
                waiters, timeout=self._poll_interval, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for waiter in waiters:
                waiter.cancel()
