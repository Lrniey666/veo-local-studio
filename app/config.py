import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_PATH = DATA_DIR / "app_config.json"
CONFIG_BACKUP_PATH = DATA_DIR / "app_config.backup.json"


DEFAULT_CONFIG = {
    "veo_api_base": "https://generativelanguage.googleapis.com/v1beta",
    "veo_api_key": "",
    "veo_model": "veo-3.1-generate-preview",
    "max_image_inputs": 8,
    "discord_bot_token": "",
    "discord_enabled": False,
    "discord_sync_guild_ids": "",   # 填伺服器 ID（可多個，以逗號分隔）可讓指令立即生效，留空則全域同步（最多 1 小時）
    "backup_apis": [],
    "cost_per_second_usd": 0.04,
    "quality_multipliers": {"720p": 1.0, "1080p": 1.4, "2k": 2.0, "4k": 3.2},
    "ntd_rate": 32.0,
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        # Fallback to backup if the main file is interrupted/corrupted.
        if CONFIG_BACKUP_PATH.exists():
            raw = json.loads(CONFIG_BACKUP_PATH.read_text(encoding="utf-8"))
        else:
            raw = {}
    merged = DEFAULT_CONFIG.copy()
    merged.update(raw)
    return merged


def save_config(data: dict) -> dict:
    merged = DEFAULT_CONFIG.copy()
    # Preserve existing keys so saving one section does not wipe others.
    if CONFIG_PATH.exists():
        try:
            existing = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                merged.update(existing)
        except Exception:
            if CONFIG_BACKUP_PATH.exists():
                try:
                    existing_bak = json.loads(CONFIG_BACKUP_PATH.read_text(encoding="utf-8"))
                    if isinstance(existing_bak, dict):
                        merged.update(existing_bak)
                except Exception:
                    pass
    merged.update(data)
    payload = json.dumps(merged, ensure_ascii=False, indent=2)
    temp_path = DATA_DIR / "app_config.tmp.json"
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(CONFIG_PATH)
    CONFIG_BACKUP_PATH.write_text(payload, encoding="utf-8")
    return merged


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 6:
        return "*" * len(key)
    return f"{key[:3]}{'*' * (len(key) - 6)}{key[-3:]}"
