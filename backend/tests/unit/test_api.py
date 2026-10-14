import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from litestar.testing import AsyncTestClient
from pydantic import SecretStr

from esfake.api.internal import create_internal_app
from esfake.api.main import create_public_app
from esfake.api.state import ModelState
from esfake.pipeline.redaction import Redactor
from esfake.shared.internal_contract import SECRET_HEADER
from tests.fakes import FakeEmbedder

SECRET = "internal-test-secret"  # noqa: S105
AUTH = {SECRET_HEADER: SECRET}


@pytest.fixture
def state() -> ModelState:
    return ModelState()


@pytest.fixture
async def public(state: ModelState) -> AsyncIterator[httpx.AsyncClient]:
    async with AsyncTestClient(create_public_app(state)) as client:
        yield client


@pytest.fixture
async def internal(state: ModelState) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_internal_app(state, SecretStr(SECRET)))
    async with httpx.AsyncClient(transport=transport, base_url="http://internal") as client:
        yield client


async def test_liveness_answers_while_the_model_loads(public: httpx.AsyncClient) -> None:
    response = await public.get("/healthz")

    assert response.status_code == 200


async def test_readiness_waits_for_the_model(public: httpx.AsyncClient, state: ModelState) -> None:
    assert (await public.get("/readyz")).status_code == 503

    await state.load(FakeEmbedder, Redactor)

    assert (await public.get("/readyz")).status_code == 200


async def test_failed_model_load_keeps_readiness_down(
    public: httpx.AsyncClient, state: ModelState
) -> None:
    def broken() -> FakeEmbedder:
        raise RuntimeError("weights missing")

    await state.load(broken, Redactor)

    assert (await public.get("/readyz")).status_code == 503


@pytest.mark.parametrize("headers", [{}, {SECRET_HEADER: "wrong"}])
async def test_internal_endpoints_require_the_shared_secret(
    internal: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    for path in ("/internal/embed", "/internal/verify"):
        response = await internal.post(path, json={"texts": ["hola"]}, headers=headers)
        assert response.status_code == 401


async def test_embed_is_unavailable_until_the_model_loads(internal: httpx.AsyncClient) -> None:
    response = await internal.post("/internal/embed", json={"texts": ["hola"]}, headers=AUTH)

    assert response.status_code == 503


async def test_embed_returns_one_vector_per_text(
    internal: httpx.AsyncClient, state: ModelState
) -> None:
    await state.load(FakeEmbedder, Redactor)

    response = await internal.post(
        "/internal/embed", json={"texts": ["hola", "chau"]}, headers=AUTH
    )

    body = response.json()
    assert response.status_code == 200
    assert body["model"] == "fake-embedder"
    assert body["dimensions"] == 384
    assert [len(vector) for vector in body["vectors"]] == [384, 384]


async def test_verify_is_not_implemented_yet(internal: httpx.AsyncClient) -> None:
    response = await internal.post("/internal/verify", headers=AUTH)

    assert response.status_code == 501


async def test_validation_errors_never_echo_the_request(internal: httpx.AsyncClient) -> None:
    canary = "CANARY-987654321"

    response = await internal.post(
        "/internal/embed", json={"texts": [canary], "unexpected": canary}, headers=AUTH
    )

    assert response.status_code == 422
    assert response.content == b""


async def test_public_app_does_not_expose_internal_routes(public: httpx.AsyncClient) -> None:
    response = await public.post("/internal/embed", json={"texts": ["hola"]}, headers=AUTH)

    assert response.status_code == 404


async def test_public_app_publishes_its_openapi_schema(public: httpx.AsyncClient) -> None:
    response = await public.get("/schema/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "¿EsFake? API"
    assert set(response.json()["paths"]) == {"/healthz", "/readyz"}


def test_building_the_apps_keeps_the_structlog_handlers(state: ModelState) -> None:
    root = logging.getLogger()
    handlers = list(root.handlers)

    create_public_app(state)
    create_internal_app(state, SecretStr(SECRET))

    assert root.handlers == handlers
