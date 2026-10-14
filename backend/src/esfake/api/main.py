"""Public listener: the only port Docker Compose publishes."""

from litestar import Litestar, Response, get
from litestar.openapi import OpenAPIConfig, ResponseSpec
from litestar.status_codes import HTTP_503_SERVICE_UNAVAILABLE

from esfake.api.errors import EXCEPTION_HANDLERS, log_unexpected
from esfake.api.state import ModelState


def create_public_app(state: ModelState) -> Litestar:
    @get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness: the process answers, whether or not the model is loaded."""
        return {"status": "ok"}

    @get(
        "/readyz",
        responses={
            HTTP_503_SERVICE_UNAVAILABLE: ResponseSpec(
                data_container=dict[str, str], description="Model still loading"
            )
        },
    )
    async def readyz() -> Response[dict[str, str]]:
        """Readiness: only once the embedding model is loaded."""
        if not state.ready:
            return Response({"status": "loading"}, status_code=HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"status": "ready"})

    return Litestar(
        route_handlers=[healthz, readyz],
        openapi_config=OpenAPIConfig(title="¿EsFake? API", version="0.1.0"),
        exception_handlers=EXCEPTION_HANDLERS,
        after_exception=[log_unexpected],
        # Litestar's default config would replace the structlog handlers on the root logger.
        logging_config=None,
    )
