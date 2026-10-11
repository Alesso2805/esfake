"""Embeddings from the API's internal listener (CLAUDE.md rule 9).

In production only the API process loads models, so the CLI sends texts to `/internal/embed`
with the shared secret, in batches the endpoint accepts. It uses the standard library, so the
runtime image needs no HTTP client.
"""

import json
import urllib.request
from collections.abc import Callable, Sequence

from pydantic import SecretStr

from esfake.api.internal import MAX_TEXTS, SECRET_HEADER, EmbedResponse

type Post = Callable[[str, bytes, dict[str, str]], bytes]

TIMEOUT_SECONDS = 120


def _post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    # The scheme is checked in InternalEmbedder.__init__, so no file:// or custom scheme gets here.
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        payload: bytes = response.read()
        return payload


class InternalEmbedder:
    def __init__(
        self,
        base_url: str,
        secret: SecretStr,
        model_name: str,
        dimensions: int,
        post: Post = _post,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("the internal URL must be http:// or https://")
        self._url = base_url.rstrip("/") + "/internal/embed"
        self._secret = secret
        self._model_name = model_name
        self._dimensions = dimensions
        self._post = post

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        headers = {
            "Content-Type": "application/json",
            SECRET_HEADER: self._secret.get_secret_value(),
        }
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_TEXTS):
            body = json.dumps({"texts": list(texts[start : start + MAX_TEXTS])}).encode()
            response = EmbedResponse.model_validate_json(self._post(self._url, body, headers))
            if (response.model, response.dimensions) != (self._model_name, self._dimensions):
                raise ValueError(
                    f"the API embeds with {response.model} ({response.dimensions} dimensions), "
                    f"but the configuration says {self._model_name} ({self._dimensions})"
                )
            vectors += response.vectors
        return vectors
