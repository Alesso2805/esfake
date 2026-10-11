"""Cache of judge responses (CLAUDE.md rule 11; ADR-0006 B). `LLMClient` (EF-10) sits on it.

The key is sha256(prompt_version | model@params | full judge input). Each response is one JSON
file under evals/llm_cache/ named by its key, so recordings from parallel PRs never conflict.
The file holds the response and usage, never the judge input, so no message text lands there.

Modes:
- `cached_strict` (CI): a missing response fails and asks for `make eval-record`.
- `record` (local, with a budget): a missing response is fetched live and saved. The caller
  marks it as live, so the gate leaves it out of the comparison.
- `live` (release, N = 3): always calls the model and never reads or writes the cache.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

type CacheMode = Literal["cached_strict", "record", "live"]


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class JudgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_version: str
    model: str
    params: dict[str, Any]
    judge_input: dict[str, Any]

    @property
    def key(self) -> str:
        joined = (
            f"{self.prompt_version}|{self.model}@{_canonical(self.params)}"
            f"|{_canonical(self.judge_input)}"
        )
        return hashlib.sha256(joined.encode()).hexdigest()


class JudgeResponse(BaseModel):
    """The judge's structured output as returned; `LLMJudge` validates its contract (EF-14)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    output: dict[str, Any]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)


class CacheEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    prompt_version: str
    model: str
    response: JudgeResponse


class MissingResponseError(LookupError):
    def __init__(self, key: str) -> None:
        super().__init__(f"no cached model response for key {key}; run `make eval-record`")


class BudgetExceededError(RuntimeError):
    pass


class ResponseCache:
    def __init__(self, directory: Path, mode: CacheMode, budget_usd: Decimal | None = None) -> None:
        self._directory = directory
        self.mode = mode
        self._budget_usd = budget_usd
        self.spent_usd = Decimal(0)
        self.live_calls = 0

    def _path(self, key: str) -> Path:
        return self._directory / key[:2] / f"{key}.json"

    async def fetch(
        self, request: JudgeRequest, call: Callable[[], Awaitable[JudgeResponse]]
    ) -> tuple[JudgeResponse, bool]:
        """Returns the response and whether it came from the cache.

        The budget is checked before each live call, so a run can exceed it by one call.
        """
        path = self._path(request.key)
        if self.mode != "live" and path.exists():
            entry = CacheEntry.model_validate_json(path.read_text(encoding="utf-8"))
            return entry.response, True
        if self.mode == "cached_strict":
            raise MissingResponseError(request.key)
        if self._budget_usd is not None and self.spent_usd >= self._budget_usd:
            raise BudgetExceededError(
                f"spent US${self.spent_usd} of the US${self._budget_usd} budget for this run"
            )
        response = await call()
        self.spent_usd += response.cost_usd
        self.live_calls += 1
        if self.mode == "record":
            entry = CacheEntry(
                key=request.key,
                prompt_version=request.prompt_version,
                model=request.model,
                response=response,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="\n") as file:
                file.write(entry.model_dump_json(indent=2) + "\n")
        return response, False
