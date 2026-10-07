from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
MODALITIES_YAML = REPO_DIR / "config" / "modalities.yaml"
CONFIG_DIR = REPO_DIR / "config"
NAMES_DEV = REPO_DIR / "evals" / "redaction" / "names.jsonl"
NAMES_VALIDATION = REPO_DIR / "evals" / "redaction" / "names_validation.jsonl"
