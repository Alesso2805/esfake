"""Both listeners run on one event loop, share the model and stop together (CLAUDE.md rule 9)."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
import uvicorn

from esfake.api.internal import SECRET_HEADER
from esfake.api.serve import build_servers, run_servers
from esfake.api.state import ModelState
from esfake.shared.config import ApiSettings
from tests.fakes import FakeEmbedder

SECRET = "internal-test-secret"  # noqa: S105


@dataclass
class RunningApi:
    state: ModelState
    public_url: str
    internal_url: str
    servers: tuple[uvicorn.Server, uvicorn.Server]
    task: asyncio.Task[None]


def _port(server: uvicorn.Server) -> int:
    port: int = server.servers[0].sockets[0].getsockname()[1]
    return port


@pytest.fixture
async def running_api() -> AsyncIterator[RunningApi]:
    settings = ApiSettings.model_validate(
        {
            "ESFAKE_INTERNAL_SECRET": SECRET,
            "ESFAKE_HOST": "127.0.0.1",
            "ESFAKE_PUBLIC_PORT": 0,
            "ESFAKE_INTERNAL_PORT": 0,
        }
    )
    state = ModelState()
    public, internal = build_servers(settings, state)
    task = asyncio.create_task(run_servers(public, internal))
    async with asyncio.timeout(10):
        while not (public.started and internal.started):  # noqa: ASYNC110 (uvicorn has no started event)
            await asyncio.sleep(0.05)
    api = RunningApi(
        state,
        f"http://127.0.0.1:{_port(public)}",
        f"http://127.0.0.1:{_port(internal)}",
        (public, internal),
        task,
    )
    yield api
    public.should_exit = True
    await asyncio.wait_for(task, timeout=10)


async def test_listeners_share_the_loaded_model(running_api: RunningApi) -> None:
    async with httpx.AsyncClient() as client:
        assert (await client.get(f"{running_api.public_url}/readyz")).status_code == 503

        await running_api.state.load(FakeEmbedder)

        assert (await client.get(f"{running_api.public_url}/readyz")).status_code == 200
        embed = await client.post(
            f"{running_api.internal_url}/internal/embed",
            json={"texts": ["hola"]},
            headers={SECRET_HEADER: SECRET},
        )
        assert embed.status_code == 200


async def test_internal_routes_live_only_on_the_internal_port(running_api: RunningApi) -> None:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{running_api.public_url}/internal/embed",
            json={"texts": ["hola"]},
            headers={SECRET_HEADER: SECRET},
        )

    assert response.status_code == 404


async def test_stopping_one_listener_stops_both(running_api: RunningApi) -> None:
    public, internal = running_api.servers

    internal.should_exit = True
    await asyncio.wait_for(running_api.task, timeout=10)

    assert public.should_exit
