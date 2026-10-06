"""Declarative base and the constraint helpers shared by every table."""

from collections.abc import Iterable

from sqlalchemy import CheckConstraint, MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names, so migrations and `alembic check` agree on every environment.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Every HMAC is stored as "<key_id>:<hex sha-256>" so lookups can try each active key during a
# rotation (docs/SPEC.md, Esquema). The format check also stops a raw identifier from being
# stored by mistake.
HMAC_PATTERN = "^[A-Za-z0-9_-]{1,32}:[0-9a-f]{64}$"

# Dataset versions are MAJOR.MINOR: deletions bump the minor, a new cluster threshold the major.
DATASET_VERSION_PATTERN = "^[0-9]+\\.[0-9]+$"

LEVELS = ("likely_scam", "suspicious", "no_signals")
ROUTES = ("early_exit", "gray_zone", "risk_trait", "out_of_distribution", "no_route")
LLM_ROUTES = ("gray_zone", "risk_trait", "out_of_distribution")
CHANNELS = ("web", "whatsapp", "telegram")
LABELS = ("scam", "legit")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def sql_in(values: Iterable[str]) -> str:
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


def one_of(column: str, values: Iterable[str]) -> CheckConstraint:
    return CheckConstraint(f"{column} IN {sql_in(values)}", name=f"{column}_valid")


def hmac_format(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} ~ '{HMAC_PATTERN}'", name=f"{column}_format")
