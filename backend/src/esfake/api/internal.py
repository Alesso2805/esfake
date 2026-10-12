"""Internal listener: never published, guarded by a shared secret (CLAUDE.md rule 9).

The channel worker calls `/internal/verify` and the CLI calls `/internal/embed`, so only the
API process loads models in production.
"""

import asyncio
import hmac
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import SecretStr

from esfake.api.errors import install_error_handlers
from esfake.api.state import ModelState
from esfake.shared.internal_contract import SECRET_HEADER, EmbedRequest, EmbedResponse


def create_internal_app(state: ModelState, secret: SecretStr) -> FastAPI:
    expected = secret.get_secret_value().encode()

    def require_secret(
        provided: Annotated[str | None, Header(alias=SECRET_HEADER)] = None,
    ) -> None:
        if provided is None or not hmac.compare_digest(provided.encode(), expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED)

    app = FastAPI(
        title="¿EsFake? internal API",
        openapi_url=None,
        dependencies=[Depends(require_secret)],
    )
    install_error_handlers(app)

    @app.post("/internal/embed")
    async def embed(request: EmbedRequest) -> EmbedResponse:
        embedder = state.embedder
        if embedder is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "model loading")
        # CPU-bound: keep the event loop, and the other listener, responsive.
        vectors = await asyncio.to_thread(embedder.embed, request.texts)
        return EmbedResponse(
            model=embedder.model_name, dimensions=embedder.dimensions, vectors=vectors
        )

    @app.post("/internal/verify")
    async def verify() -> None:
        """Runs the pipeline for the channel worker once it exists (EF-11 to EF-15)."""
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "pipeline not implemented yet")

    return app
