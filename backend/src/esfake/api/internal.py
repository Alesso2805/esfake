"""Internal listener: never published, guarded by a shared secret (CLAUDE.md rule 9).

The channel worker calls `/internal/verify` and the CLI calls `/internal/embed`, so only the
API process loads models in production.
"""

import asyncio
import hmac
from typing import Any

from litestar import Litestar, post
from litestar.connection import ASGIConnection
from litestar.exceptions import HTTPException, NotAuthorizedException, ServiceUnavailableException
from litestar.handlers import BaseRouteHandler
from litestar.status_codes import HTTP_200_OK, HTTP_501_NOT_IMPLEMENTED
from pydantic import SecretStr

from esfake.api.errors import EXCEPTION_HANDLERS, log_unexpected
from esfake.api.state import ModelState
from esfake.shared.internal_contract import SECRET_HEADER, EmbedRequest, EmbedResponse


def create_internal_app(state: ModelState, secret: SecretStr) -> Litestar:
    expected = secret.get_secret_value().encode()

    def require_secret(connection: ASGIConnection[Any, Any, Any, Any], _: BaseRouteHandler) -> None:
        # Guards run before the body is read: without the secret, an invalid body is still a 401.
        provided = connection.headers.get(SECRET_HEADER)
        if provided is None or not hmac.compare_digest(provided.encode(), expected):
            raise NotAuthorizedException

    # Litestar answers POST with 201 by default; the internal contract is 200.
    @post("/internal/embed", status_code=HTTP_200_OK)
    async def embed(data: EmbedRequest) -> EmbedResponse:
        embedder = state.embedder
        if embedder is None:
            raise ServiceUnavailableException(detail="model loading")
        # CPU-bound: keep the event loop, and the other listener, responsive.
        vectors = await asyncio.to_thread(embedder.embed, data.texts)
        return EmbedResponse(
            model=embedder.model_name, dimensions=embedder.dimensions, vectors=vectors
        )

    @post("/internal/verify", status_code=HTTP_200_OK)
    async def verify() -> None:
        """Runs the pipeline for the channel worker once it exists (EF-11 to EF-15)."""
        raise HTTPException(
            status_code=HTTP_501_NOT_IMPLEMENTED, detail="pipeline not implemented yet"
        )

    return Litestar(
        route_handlers=[embed, verify],
        guards=[require_secret],
        openapi_config=None,
        exception_handlers=EXCEPTION_HANDLERS,
        after_exception=[log_unexpected],
        # Litestar's default config would replace the structlog handlers on the root logger.
        logging_config=None,
    )
