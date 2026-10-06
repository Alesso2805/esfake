"""Background workers: channel delivery and maintenance."""

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable


async def run_until_signal(run: Callable[[asyncio.Event], Awaitable[None]]) -> None:
    """Run a worker until SIGTERM or SIGINT, letting it finish its current step."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        # Containers run on Linux; Windows event loops do not support signal handlers.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop.set)
    await run(stop)
