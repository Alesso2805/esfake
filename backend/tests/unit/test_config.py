from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from esfake.shared.clock import FakeClock
from esfake.shared.config import ApiSettings, CorpusImportSettings

DEV_SECRET = "dev-insecure-internal-secret"  # noqa: S105


def test_development_accepts_the_compose_defaults() -> None:
    settings = ApiSettings.model_validate({"ESFAKE_INTERNAL_SECRET": DEV_SECRET})

    assert settings.env == "development"
    assert settings.trusted_proxy_list == []


def test_production_refuses_development_secrets_without_echoing_them() -> None:
    with pytest.raises(ValidationError) as error:
        ApiSettings.model_validate(
            {"ESFAKE_ENV": "production", "ESFAKE_INTERNAL_SECRET": DEV_SECRET}
        )

    assert "internal_secret still uses a development default" in str(error.value)
    assert DEV_SECRET not in str(error.value)


def test_trusted_proxies_are_an_explicit_list() -> None:
    settings = ApiSettings.model_validate(
        {"ESFAKE_INTERNAL_SECRET": "s", "ESFAKE_TRUSTED_PROXIES": "10.0.0.2, 10.0.0.3,"}
    )

    assert settings.trusted_proxy_list == ["10.0.0.2", "10.0.0.3"]


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"ESFAKE_ENV": "production"}, "asks /internal/embed"),
        ({"ESFAKE_INTERNAL_URL": "http://api:8001"}, "needs ESFAKE_INTERNAL_SECRET"),
    ],
)
def test_corpus_import_never_loads_models_in_production(values: dict[str, str], error: str) -> None:
    # CLAUDE.md rule 9: in production only the API loads models; the CLI asks /internal/embed.
    base = {"DATABASE_URL": "postgresql+asyncpg://app@db/esfake", "ESFAKE_ACTOR": "owner"}

    with pytest.raises(ValidationError, match=error):
        CorpusImportSettings.model_validate(base | values)


def test_fake_clock_moves_only_when_told() -> None:
    clock = FakeClock(datetime(2026, 10, 6, tzinfo=UTC))

    clock.advance(timedelta(seconds=60))

    assert clock.now() == datetime(2026, 10, 6, 0, 1, tzinfo=UTC)


def test_fake_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 10, 6))  # noqa: DTZ001
