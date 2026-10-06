import asyncio
from datetime import UTC, datetime

from esfake.shared.clock import FakeClock
from esfake.workers.channels import asyncpg_dsn
from esfake.workers.maintenance import MaintenanceWorker

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def test_asyncpg_dsn_drops_the_sqlalchemy_driver() -> None:
    dsn = asyncpg_dsn("postgresql+asyncpg://esfake_app:secret@db:5432/esfake")

    assert dsn == "postgresql://esfake_app:secret@db:5432/esfake"


async def test_jobs_run_with_the_clock_time() -> None:
    stop = asyncio.Event()
    seen: list[datetime] = []

    async def job(now: datetime) -> None:
        seen.append(now)
        stop.set()

    await asyncio.wait_for(MaintenanceWorker(FakeClock(NOW), [job]).run(stop), timeout=5)

    assert seen == [NOW]


async def test_a_failing_job_does_not_stop_the_others() -> None:
    stop = asyncio.Event()
    ran: list[str] = []

    async def broken(_now: datetime) -> None:
        raise RuntimeError("boom")

    async def healthy(_now: datetime) -> None:
        ran.append("healthy")
        stop.set()

    await asyncio.wait_for(MaintenanceWorker(FakeClock(NOW), [broken, healthy]).run(stop), 5)

    assert ran == ["healthy"]
