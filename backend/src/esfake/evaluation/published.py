"""Published evaluations in docs/evals/<version>.json (EF-08; ADR-0006 B).

Versions are `v0` (policy v0), then `v0.1`, `v0.2`… and `v1.0` at the release. Each file keeps
the manifest, the metrics and the per-case predictions (case_id, level, route): the gate of
every later PR compares against them without running old code again.
"""

import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from esfake.evaluation.gate import Baseline
from esfake.evaluation.metrics import CasePrediction, Metrics
from esfake.pipeline.manifest import Manifest
from esfake.pipeline.verdict import Level, Route

VERSION_PATTERN = re.compile(r"^v(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?$")


def version_key(version: str) -> tuple[int, int]:
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise ValueError(f"{version!r} is not a version such as v0, v0.1 or v1.0")
    return int(match[1]), int(match[2] or 0)


class PublishedCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    level: Level
    route: Route


class PublishedEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(pattern=VERSION_PATTERN.pattern)
    suite: Literal["eval"] = "eval"
    published_at: date
    manifest_hash: str
    manifest: Manifest
    metrics: Metrics
    predictions: tuple[PublishedCase, ...]

    def baseline(self) -> Baseline:
        return Baseline(
            version=self.version, levels={case.case_id: case.level for case in self.predictions}
        )


def _path(evals_dir: Path, version: str) -> Path:
    return evals_dir / f"{version}.json"


def published_versions(evals_dir: Path) -> list[str]:
    if not evals_dir.is_dir():
        return []
    versions = [p.stem for p in evals_dir.glob("v*.json") if VERSION_PATTERN.fullmatch(p.stem)]
    return sorted(versions, key=version_key)


def latest_published(evals_dir: Path) -> PublishedEvaluation | None:
    versions = published_versions(evals_dir)
    if not versions:
        return None
    text = _path(evals_dir, versions[-1]).read_text(encoding="utf-8")
    return PublishedEvaluation.model_validate_json(text)


def publish(
    evals_dir: Path,
    version: str,
    published_at: date,
    manifest: Manifest,
    metrics: Metrics,
    predictions: list[CasePrediction],
) -> Path:
    """Write a new version; it must sort after every version already published."""
    latest = published_versions(evals_dir)
    if latest and version_key(version) <= version_key(latest[-1]):
        raise ValueError(f"{version} must come after the latest published version, {latest[-1]}")
    evaluation = PublishedEvaluation(
        version=version,
        published_at=published_at,
        manifest_hash=manifest.hash,
        manifest=manifest,
        metrics=metrics,
        predictions=tuple(
            PublishedCase(case_id=p.case_id, level=p.level, route=p.route)
            for p in sorted(predictions, key=lambda p: p.case_id)
        ),
    )
    path = _path(evals_dir, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        file.write(evaluation.model_dump_json(indent=2) + "\n")
    return path
