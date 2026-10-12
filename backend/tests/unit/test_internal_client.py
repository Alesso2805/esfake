import asyncio
import json
from urllib.parse import urlsplit

import httpx
import pytest
from pydantic import SecretStr

from esfake.api.internal import create_internal_app
from esfake.api.state import ModelState
from esfake.pipeline.similarity.internal_client import InternalEmbedder
from tests.fakes import FakeEmbedder

SECRET = SecretStr("internal-test-secret")


def internal_api(secret: SecretStr = SECRET) -> tuple[list[int], InternalEmbedder]:
    """An InternalEmbedder wired to the real internal app, recording the size of each batch."""
    state = ModelState()
    state.embedder = FakeEmbedder()
    api = create_internal_app(state, SECRET)
    batches: list[int] = []

    def post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        batches.append(len(json.loads(body)["texts"]))

        async def send() -> bytes:
            transport = httpx.ASGITransport(app=api)
            async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
                response = await client.post(urlsplit(url).path, content=body, headers=headers)
            response.raise_for_status()
            return response.content

        return asyncio.run(send())

    return batches, InternalEmbedder("http://api:8001", secret, "fake-embedder", 384, post=post)


def test_texts_go_to_the_internal_listener_in_accepted_batches() -> None:
    batches, embedder = internal_api()

    vectors = embedder.embed([f"mensaje {i}" for i in range(130)])

    assert batches == [64, 64, 2]
    assert len(vectors) == 130
    assert len(vectors[0]) == 384


def test_a_wrong_secret_is_refused() -> None:
    _, embedder = internal_api(SecretStr("not-the-secret"))

    with pytest.raises(Exception, match="401"):
        embedder.embed(["hola"])


def test_the_api_must_run_the_configured_model() -> None:
    _, embedder = internal_api()
    mismatched = InternalEmbedder(
        "http://api:8001", SECRET, "another-model", 384, post=embedder._post
    )

    with pytest.raises(ValueError, match="the configuration says another-model"):
        mismatched.embed(["hola"])


def test_only_http_urls_are_accepted() -> None:
    with pytest.raises(ValueError, match="http"):
        InternalEmbedder("file:///etc/passwd", SECRET, "fake-embedder", 384)
