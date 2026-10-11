from decimal import Decimal
from pathlib import Path

import pytest

from esfake.pipeline.llm.cache import (
    BudgetExceededError,
    JudgeRequest,
    JudgeResponse,
    MissingResponseError,
    ResponseCache,
)

REQUEST = JudgeRequest(
    prompt_version="judge-v1",
    model="claude-haiku-4-5",
    params={"temperature": 0, "max_tokens": 200},
    judge_input={"message": "Ganaste un premio", "signals": ["prize"]},
)
RESPONSE = JudgeResponse(
    output={"level": "suspicious", "codes": ["prize"]},
    input_tokens=120,
    output_tokens=15,
    cost_usd=Decimal("0.0002"),
)


class FakeModel:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> JudgeResponse:
        self.calls += 1
        return RESPONSE


def stored_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.json"))


def test_the_key_hashes_prompt_model_params_and_the_full_input() -> None:
    reordered = REQUEST.model_copy(update={"params": {"max_tokens": 200, "temperature": 0}})

    assert REQUEST.key == reordered.key
    assert len(REQUEST.key) == 64
    for change in (
        {"prompt_version": "judge-v2"},
        {"model": "other"},
        {"params": {"temperature": 0.2, "max_tokens": 200}},
        {"judge_input": {"message": "Ganaste un premio", "signals": []}},
    ):
        assert REQUEST.model_copy(update=change).key != REQUEST.key


async def test_cached_strict_fails_on_a_missing_response_without_calling(tmp_path: Path) -> None:
    model = FakeModel()

    with pytest.raises(MissingResponseError, match="make eval-record"):
        await ResponseCache(tmp_path, "cached_strict").fetch(REQUEST, model)
    assert model.calls == 0


async def test_record_saves_what_cached_strict_then_reads(tmp_path: Path) -> None:
    model = FakeModel()
    recorder = ResponseCache(tmp_path, "record")

    recorded, cached = await recorder.fetch(REQUEST, model)
    replayed, replay_cached = await ResponseCache(tmp_path, "cached_strict").fetch(REQUEST, model)

    assert (recorded, cached) == (RESPONSE, False)
    assert (replayed, replay_cached) == (RESPONSE, True)
    assert (model.calls, recorder.live_calls, recorder.spent_usd) == (1, 1, Decimal("0.0002"))
    [path] = stored_files(tmp_path)
    assert path.name == f"{REQUEST.key}.json"
    stored = path.read_bytes()
    assert b"\r\n" not in stored
    assert b"Ganaste" not in stored  # the judge input, with message text, is never stored


async def test_live_mode_always_calls_and_never_writes(tmp_path: Path) -> None:
    model = FakeModel()
    await ResponseCache(tmp_path, "record").fetch(REQUEST, model)

    _, cached = await ResponseCache(tmp_path, "live").fetch(
        REQUEST.model_copy(update={"model": "other"}), model
    )
    _, cached_again = await ResponseCache(tmp_path, "live").fetch(REQUEST, model)

    assert (cached, cached_again, model.calls) == (False, False, 3)
    assert len(stored_files(tmp_path)) == 1


async def test_record_stops_at_the_budget(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path, "record", budget_usd=Decimal("0.0002"))
    await cache.fetch(REQUEST, FakeModel())

    with pytest.raises(BudgetExceededError, match="budget"):
        await cache.fetch(REQUEST.model_copy(update={"model": "other"}), FakeModel())
