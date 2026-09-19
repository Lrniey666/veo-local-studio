"""
使用紀錄服務
同時寫入：
  data/usage_log.csv   — 機器可讀的逐行紀錄
  data/usage_log.json  — 結構化全量紀錄（JSON 陣列）
"""
import csv
import json
import threading
from datetime import datetime
from typing import Any

from ..paths import DATA_DIR, ensure_runtime_dirs

ensure_runtime_dirs()

CSV_PATH  = DATA_DIR / "usage_log.csv"
JSON_PATH = DATA_DIR / "usage_log.json"

_lock = threading.Lock()

# ─── CSV 欄位定義（依序）────────────────────────────────────────────────────

CSV_FIELDS = [
    "timestamp",            # ISO 8601
    "source",               # "discord" | "desktop" | "api"
    "discord_user_name",
    "discord_user_id",
    "discord_guild_name",
    "discord_guild_id",
    "discord_channel_name",
    "discord_channel_id",
    "conversation_id",
    "command_id",
    "gen_type",             # text_to_video / image_to_video / ...
    "gen_type_label",       # 中文標籤
    "prompt_preview",       # 前 200 字
    "duration_seconds",
    "aspect_ratio",
    "quality",
    "estimated_tokens",
    "estimated_cost_usd",
    "estimated_cost_ntd",
    "elapsed_seconds",
    "status",               # "done" | "error"
    "error_message",        # 錯誤時填入
    "video_path",
    "provider",             # primary / backup-1 / ...
]


def _ensure_csv_header():
    """若 CSV 不存在或為空則寫入標頭列。"""
    if not CSV_PATH.exists() or CSV_PATH.stat().st_size == 0:
        with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            w.writeheader()


def _load_json_log() -> list[dict]:
    if JSON_PATH.exists():
        try:
            data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def log_usage(
    *,
    source: str = "desktop",
    # Discord 來源資訊（非 Discord 時可省略）
    discord_user_name: str = "",
    discord_user_id: str = "",
    discord_guild_name: str = "",
    discord_guild_id: str = "",
    discord_channel_name: str = "",
    discord_channel_id: str = "",
    # 紀錄識別
    conversation_id: int | None = None,
    command_id: int | None = None,
    # 生成參數
    gen_type: str = "text_to_video",
    prompt: str = "",
    duration_seconds: int = 8,
    aspect_ratio: str = "16:9",
    quality: str = "1080p",
    # 費用估算
    estimated_tokens: int = 0,
    estimated_cost_usd: float = 0.0,
    estimated_cost_ntd: float = 0.0,
    # 結果
    elapsed_seconds: float = 0.0,
    status: str = "done",
    error_message: str = "",
    video_path: str = "",
    provider: str = "",
    # 額外自訂欄位（寫入 JSON 的 extra 鍵）
    extra: dict[str, Any] | None = None,
):
    from ..services.veo_client import GEN_TYPE_LABELS

    ts = datetime.now().isoformat(timespec="seconds")
    row: dict[str, Any] = {
        "timestamp":             ts,
        "source":                source,
        "discord_user_name":     discord_user_name,
        "discord_user_id":       discord_user_id,
        "discord_guild_name":    discord_guild_name,
        "discord_guild_id":      discord_guild_id,
        "discord_channel_name":  discord_channel_name,
        "discord_channel_id":    discord_channel_id,
        "conversation_id":       conversation_id,
        "command_id":            command_id,
        "gen_type":              gen_type,
        "gen_type_label":        GEN_TYPE_LABELS.get(gen_type, gen_type),
        "prompt_preview":        prompt[:200],
        "duration_seconds":      duration_seconds,
        "aspect_ratio":          aspect_ratio,
        "quality":               quality,
        "estimated_tokens":      estimated_tokens,
        "estimated_cost_usd":    round(estimated_cost_usd, 4),
        "estimated_cost_ntd":    round(estimated_cost_ntd, 2),
        "elapsed_seconds":       round(elapsed_seconds, 2),
        "status":                status,
        "error_message":         error_message[:300] if error_message else "",
        "video_path":            video_path,
        "provider":              provider,
    }
    if extra:
        row["extra"] = extra

    with _lock:
        # ── CSV ─────────────────────────────────────────────────────────────
        try:
            _ensure_csv_header()
            with CSV_PATH.open("a", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
                w.writerow(row)
        except Exception as exc:
            print(f"[usage_logger] CSV 寫入失敗：{exc}")

        # ── JSON ─────────────────────────────────────────────────────────────
        try:
            records = _load_json_log()
            records.append(row)
            JSON_PATH.write_text(
                json.dumps(records, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[usage_logger] JSON 寫入失敗：{exc}")


def read_recent(n: int = 100) -> list[dict]:
    """讀取最近 n 筆紀錄（從 JSON）。"""
    records = _load_json_log()
    return records[-n:]


def summary_stats() -> dict[str, Any]:
    """回傳彙總統計（總筆數、成功/失敗、總費用）。"""
    records = _load_json_log()
    total   = len(records)
    done    = sum(1 for r in records if r.get("status") == "done")
    error   = total - done
    total_ntd = sum(float(r.get("estimated_cost_ntd", 0)) for r in records)
    total_usd = sum(float(r.get("estimated_cost_usd", 0)) for r in records)
    total_tokens = sum(int(r.get("estimated_tokens", 0)) for r in records)
    return {
        "total":        total,
        "done":         done,
        "error":        error,
        "total_tokens": total_tokens,
        "total_usd":    round(total_usd, 4),
        "total_ntd":    round(total_ntd, 2),
    }
