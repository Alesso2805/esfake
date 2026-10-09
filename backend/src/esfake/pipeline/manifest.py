"""The pipeline manifest (CLAUDE.md rule 12): exactly what produced a verdict or an evaluation.

Its hash is the SHA-256 of the canonical JSON of every field, so two runs share a hash only when
commit, models, parameters, prompt, redactor, thresholds and index snapshot all match.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from esfake.pipeline.redaction import REDACTOR_VERSION
from esfake.shared.models_config import load_models_config
from esfake.shared.thresholds import load_thresholds


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    git_sha: str
    embedding_model: str
    llm_model: str | None
    llm_params: dict[str, Any] | None
    prompt_version: str | None
    redactor_version: str
    thresholds_version: str
    index_snapshot: str

    @property
    def hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def index_snapshot(case_ids: Iterable[str]) -> str:
    """Fingerprint of the similarity index: the sorted case_ids of the `index` split."""
    return hashlib.sha256("\n".join(sorted(case_ids)).encode()).hexdigest()


def build_manifest(config_dir: Path, git_sha: str, index_case_ids: Iterable[str]) -> Manifest:
    # The judge arrives with EF-14; until then the manifest names no model and no prompt.
    return Manifest(
        git_sha=git_sha,
        embedding_model=load_models_config(config_dir).embedding.name,
        llm_model=None,
        llm_params=None,
        prompt_version=None,
        redactor_version=REDACTOR_VERSION,
        thresholds_version=load_thresholds(config_dir).version,
        index_snapshot=index_snapshot(index_case_ids),
    )
