import secrets
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = BASE_DIR / "outputs"
INPUTS_DIR = OUTPUT_DIR / "inputs"
VIDEOS_DIR = OUTPUT_DIR / "videos"

for folder in (OUTPUT_DIR, INPUTS_DIR, VIDEOS_DIR):
    folder.mkdir(parents=True, exist_ok=True)


def unique_name(prefix: str, suffix: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    token = secrets.token_hex(4)
    return f"{prefix}_{ts}_{token}{suffix}"


def save_uploaded_image(data: bytes, suffix: str) -> Path:
    suffix = suffix if suffix.startswith(".") else f".{suffix or 'png'}"
    path = INPUTS_DIR / unique_name("input", suffix)
    path.write_bytes(data)
    return path


def save_video(data: bytes, suffix: str = ".mp4") -> Path:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    path = VIDEOS_DIR / unique_name("veo_video", suffix)
    path.write_bytes(data)
    return path
