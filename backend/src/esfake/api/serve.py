"""Two uvicorn servers on one event loop, sharing the loaded models (CLAUDE.md rule 9).

The public server is the only one Docker Compose publishes. The internal one listens on its own
port inside the private network and never trusts forwarded headers.
"""

import asyncio
from collections.abc import Callable

import uvicorn

from esfake.api.internal import create_internal_app
from esfake.api.main import create_public_app
from esfake.api.state import ModelState
from esfake.pipeline.redaction import Redactor
from esfake.pipeline.similarity.embedder import Embedder
from esfake.shared.config import ApiSettings


def build_servers(
    settings: ApiSettings, state: ModelState
) -> tuple[uvicorn.Server, uvicorn.Server]:
    trusted = settings.trusted_proxy_list
    public = uvicorn.Server(
        uvicorn.Config(
            create_public_app(state),
            host=settings.host,
            port=settings.public_port,
            # The client IP comes only from an explicit list of trusted proxies.
            proxy_headers=bool(trusted),
            forwarded_allow_ips=trusted or None,
            server_header=False,
            log_config=None,
        )
    )
    internal = uvicorn.Server(
        uvicorn.Config(
            create_internal_app(state, settings.internal_secret),
            host=settings.host,
            port=settings.internal_port,
            proxy_headers=False,
            server_header=False,
            log_config=None,
        )
    )
    return public, internal


async def run_servers(*servers: uvicorn.Server) -> None:
    """Run until any server stops, then stop the others.

    Each uvicorn server captures SIGTERM and SIGINT while it runs and re-raises them on exit, so
    one signal stops every server in turn; stopping the rest here also covers a crash.
    """
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for server in servers:
        server.should_exit = True
    await asyncio.gather(*tasks)


async def serve(
    settings: ApiSettings,
    embedder_factory: Callable[[], Embedder],
    redactor_factory: Callable[[], Redactor],
) -> None:
    state = ModelState()
    public, internal = build_servers(settings, state)
    loading = asyncio.create_task(state.load(embedder_factory, redactor_factory))
    try:
        await run_servers(public, internal)
    finally:
        loading.cancel()
