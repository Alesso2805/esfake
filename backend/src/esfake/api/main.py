"""Public listener: the only port Docker Compose publishes."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from esfake.api.errors import install_error_handlers
from esfake.api.state import ModelState


def create_public_app(state: ModelState) -> FastAPI:
    app = FastAPI(title="¿EsFake? API", version="0.1.0")
    install_error_handlers(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness: the process answers, whether or not the model is loaded."""
        return {"status": "ok"}

    @app.get("/readyz", responses={503: {"description": "Model still loading"}})
    async def readyz() -> JSONResponse:
        """Readiness: only once the embedding model is loaded."""
        if not state.ready:
            return JSONResponse({"status": "loading"}, status_code=503)
        return JSONResponse({"status": "ready"})

    return app
