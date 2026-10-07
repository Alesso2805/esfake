"""LISTEN/NOTIFY over a direct connection, with the polling fallback (ADR-0002 §2)."""

import asyncio
from collections.abc import AsyncIterator, Callable

import asyncpg
import pytest

from esfake.workers.channels import QUEUE_CHANNEL, ChannelWorker, asyncpg_dsn
from tests.integration.conftest import Database

type StartWorker = Callable[[float], asyncio.Queue[None]]


@pytest.fixture
async def start_worker(database: Database) -> AsyncIterator[StartWorker]:
    stop = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []

    def start(poll_interval: float) -> asyncio.Queue[None]:
        wakes: asyncio.Queue[None] = asyncio.Queue()

        async def on_wake() -> None:
            await wakes.put(None)

        worker = ChannelWorker(asyncpg_dsn(database.app_url), on_wake, poll_interval=poll_interval)
        tasks.append(asyncio.create_task(worker.run(stop)))
        return wakes

    yield start
    stop.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)


async def test_notify_wakes_the_worker_long_before_the_poll(
    database: Database, start_worker: StartWorker
) -> None:
    wakes = start_worker(60.0)
    await asyncio.wait_for(wakes.get(), timeout=10)  # the drain on startup

    connection = await asyncpg.connect(asyncpg_dsn(database.app_url))
    try:
        await connection.execute("SELECT pg_notify($1, '')", QUEUE_CHANNEL)
    finally:
        await connection.close()

    await asyncio.wait_for(wakes.get(), timeout=2)


async def test_polling_wakes_the_worker_without_notifications(start_worker: StartWorker) -> None:
    wakes = start_worker(0.2)

    for _ in range(3):
        await asyncio.wait_for(wakes.get(), timeout=5)
