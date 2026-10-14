import json
import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from litestar.handlers import HTTPRouteHandler
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
JSON = {"content-type": "application/json"}
# Synthetic personal data: none of it may come back in an error response.
DNI = "45678912"
ACCOUNT = "191-98765432-0-55"
PERSONAL = f"Mi DNI es {DNI} y mi cuenta BCP es {ACCOUNT}"


@pytest.fixture
def state() -> ModelState:
    return ModelState()


@pytest.fixture
async def public(state: ModelState) -> AsyncIterator[httpx.AsyncClient]:
    async with AsyncTestClient(create_public_app(state)) as client:
        yield client


@pytest.fixture
async def internal(state: ModelState) -> AsyncIterator[httpx.AsyncClient]:
    async with AsyncTestClient(create_internal_app(state, SecretStr(SECRET))) as client:
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


@pytest.mark.parametrize("headers", [{}, {SECRET_HEADER: "wrong"}])
async def test_the_secret_is_checked_before_the_body(
    internal: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await internal.post(
        "/internal/embed", content=b'{"texts": "not a list"', headers={**JSON, **headers}
    )

    assert response.status_code == 401


def test_internal_posts_answer_200_not_201(state: ModelState) -> None:
    app = create_internal_app(state, SecretStr(SECRET))

    statuses = {
        path: handler.status_code
        for path, methods in app.route_handler_method_map.items()
        for method, handler in methods.items()
        if method == "POST" and isinstance(handler, HTTPRouteHandler)
    }

    # /internal/verify still raises 501, so its declared status is what can be checked today.
    assert statuses == {"/internal/embed": 200, "/internal/verify": 200}


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


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"texts": PERSONAL}),
        json.dumps({"texts": [PERSONAL], "reply_to": PERSONAL}),
        json.dumps({"texts": [PERSONAL * 100]}),
        '{"texts": ["' + PERSONAL + '"',
    ],
    ids=["not a list", "unknown field", "text too long", "not JSON"],
)
async def test_invalid_bodies_with_personal_data_get_an_empty_422(
    internal: httpx.AsyncClient, body: str
) -> None:
    response = await internal.post(
        "/internal/embed", content=body.encode(), headers={**AUTH, **JSON}
    )

    assert response.status_code == 422
    assert response.content == b""
    assert not any(DNI in value or ACCOUNT in value for value in response.headers.values())


async def test_internal_app_publishes_no_openapi_schema(internal: httpx.AsyncClient) -> None:
    response = await internal.get("/schema/openapi.json", headers=AUTH)

    assert response.status_code == 404


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
