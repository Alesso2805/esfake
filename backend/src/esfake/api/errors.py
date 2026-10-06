"""Validation errors never echo the request (CLAUDE.md rule 4).

FastAPI's default 422 body repeats every invalid input, which here can be message text.
"""

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError


async def _validation_error(_request: Request, _exc: Exception) -> Response:
    return Response(status_code=422)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error)
