from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent
MODALITIES_YAML = REPO_DIR / "config" / "modalities.yaml"
