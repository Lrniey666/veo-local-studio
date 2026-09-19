"""Idempotent SQLite column upgrades for existing command rows."""
import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.paths import DATA_DIR, ensure_runtime_dirs  # noqa: E402

ensure_runtime_dirs()
DB_PATH = DATA_DIR / "veo_app.db"

NEW_COLS = [
    ("gen_type", "TEXT DEFAULT 'text_to_video'"),
    ("estimated_tokens", "INTEGER"),
    ("estimated_cost_usd", "TEXT"),
    ("estimated_cost_ntd", "TEXT"),
    ("elapsed_seconds", "TEXT"),
    ("discord_user", "TEXT"),
    ("discord_guild", "TEXT"),
    ("discord_channel", "TEXT"),
]

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='commands'")
if cur.fetchone() is None:
    print("尚無 commands 資料表，啟動桌面程式時會自動建立。")
    conn.close()
    raise SystemExit(0)

cur.execute("PRAGMA table_info(commands)")
existing = [row[1] for row in cur.fetchall()]
print("現有欄位:", existing)

for col, col_type in NEW_COLS:
    if col not in existing:
        cur.execute(f"ALTER TABLE commands ADD COLUMN {col} {col_type}")
        print(f"  + 新增欄位: {col}")
    else:
        print(f"  ✓ 已存在: {col}")

conn.commit()
conn.close()
print("\n資料庫遷移完成！")
