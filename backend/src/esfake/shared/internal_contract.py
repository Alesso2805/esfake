"""Contract of the API's internal listener, shared by the server and its clients.

It lives here, below both `api` and `pipeline`, so a client never imports the server
(docs/ARCHITECTURE_RULES.md, rule 2). Every model hides its input in errors (CLAUDE.md rule 4);
tests/unit/test_api_models.py checks this module together with `esfake.api`.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SECRET_HEADER = "X-Internal-Secret"  # noqa: S105 (a header name, not a secret)
MAX_TEXTS = 64
MAX_TEXT_LENGTH = 4_000


class EmbedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    texts: list[Annotated[str, StringConstraints(min_length=1, max_length=MAX_TEXT_LENGTH)]] = (
        Field(min_length=1, max_length=MAX_TEXTS)
    )


class EmbedResponse(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    model: str
    dimensions: int
    vectors: list[list[float]]
