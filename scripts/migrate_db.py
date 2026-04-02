"""
資料庫遷移腳本 — 新增 gen_type 等欄位到 commands 資料表
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "veo_app.db"

NEW_COLS = [
    ("gen_type",           "TEXT DEFAULT 'text_to_video'"),
    ("estimated_tokens",   "INTEGER"),
    ("estimated_cost_usd", "TEXT"),
    ("estimated_cost_ntd", "TEXT"),
    ("elapsed_seconds",    "TEXT"),
    ("discord_user",       "TEXT"),
    ("discord_guild",      "TEXT"),
    ("discord_channel",    "TEXT"),
]

conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

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
