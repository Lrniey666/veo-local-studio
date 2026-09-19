"""Repository paths. Secrets and generated files stay outside git."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"
DATA_DIR = Path(os.environ.get("VEO_STUDIO_DATA", ROOT / "data"))
OUTPUT_DIR = Path(os.environ.get("VEO_STUDIO_OUTPUTS", ROOT / "outputs"))
INPUTS_DIR = OUTPUT_DIR / "inputs"
VIDEOS_DIR = OUTPUT_DIR / "videos"


def ensure_runtime_dirs() -> None:
    for folder in (DATA_DIR, OUTPUT_DIR, INPUTS_DIR, VIDEOS_DIR):
        folder.mkdir(parents=True, exist_ok=True)
