"""Error responses never echo the request (CLAUDE.md rule 4).

Litestar answers invalid input with 400 and a body that names each failing field, which here can
sit next to message text. Every client-data error becomes 422 with an empty body instead.
"""

import traceback
from typing import Any

import structlog
from litestar import Request, Response
from litestar.enums import MediaType
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST, HTTP_422_UNPROCESSABLE_ENTITY
from litestar.types import ExceptionHandlersMap, Scope

log = structlog.get_logger(__name__)


def _invalid_request(_request: Request[Any, Any, Any], _exc: Exception) -> Response[bytes]:
    # b"", not None: Litestar serialises None to "null".
    return Response(b"", status_code=HTTP_422_UNPROCESSABLE_ENTITY, media_type=MediaType.TEXT)


# Keyed by status, not by ValidationException: a body that is not JSON raises a bare
# ClientException, also 400. Litestar matches status codes before exception types, so 401 and 404
# keep their own handling.
EXCEPTION_HANDLERS: ExceptionHandlersMap = {HTTP_400_BAD_REQUEST: _invalid_request}


def log_unexpected(exc: Exception, scope: Scope) -> None:
    """Log an exception Litestar turned into a 500, without its message.

    The apps run with `logging_config=None`, because Litestar's default config would replace the
    structlog handlers, so nothing else logs these. The message is left out: it may quote text.
    """
    if isinstance(exc, HTTPException):
        return
    log.error(
        "unhandled exception",
        path=scope["path"],
        error=type(exc).__name__,
        stack="".join(traceback.format_tb(exc.__traceback__)),
    )
