"""Capture desktop windows for README screenshots. Uses a disposable data dir."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CAPTURE_HOME = Path(tempfile.mkdtemp(prefix="veo-studio-docs-"))
os.environ["VEO_STUDIO_DATA"] = str(CAPTURE_HOME / "data")
os.environ["VEO_STUDIO_OUTPUTS"] = str(CAPTURE_HOME / "outputs")

from PIL import Image  # noqa: E402
import ctypes  # noqa: E402
from ctypes import wintypes  # noqa: E402

from app.config import save_config  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.desktop import VeoDesktopApp  # noqa: E402
from app.models import CommandRecord, Conversation  # noqa: E402
from app.paths import ensure_runtime_dirs  # noqa: E402

OUT_DIR = ROOT / "docs" / "assets"
OUT_DIR.mkdir(parents=True, exist_ok=True)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
user32.SetProcessDPIAware()
GA_ROOT = 2
PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _root_hwnd(widget) -> int:
    hwnd = int(widget.winfo_id())
    return int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)


def capture_widget(widget, dest: Path) -> None:
    widget.update_idletasks()
    widget.update()
    widget.lift()
    widget.focus_force()
    widget.update()
    hwnd = _root_hwnd(widget)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)

    hwnd_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    gdi32.SelectObject(mem_dc, bmp)
    painted = user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
    if not painted:
        gdi32.BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, 0, 0, SRCCOPY)

    info = BITMAPINFO()
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(info), 0)
    image = Image.frombuffer("RGB", (width, height), buf, "raw", "BGRX", 0, 1).copy()
    image.save(dest, "PNG")
    print(f"saved {dest} {image.size}")

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)


def seed_demo() -> None:
    ensure_runtime_dirs()
    Base.metadata.create_all(bind=engine)
    save_config(
        {
            "veo_api_base": "https://generativelanguage.googleapis.com/v1beta",
            "veo_api_key": "",
            "veo_model": "veo-3.1-generate-preview",
            "max_image_inputs": 8,
            "discord_enabled": False,
            "discord_bot_token": "",
            "ui_theme": "dark",
            "ui_state": {
                "prompt_draft": (
                    "黃昏海岸，低角度跟拍一名穿亞麻外套的旅人走在潮線上。"
                    "鏡頭緩緩前推，浪花濺到鏡頭邊緣，暖色長陰影，電影感顆粒。"
                ),
                "duration_seconds": "8",
                "aspect_ratio": "16:9",
                "quality": "1080p",
                "gen_type": "text_to_video",
            },
        }
    )
    db = SessionLocal()
    try:
        coast = Conversation(title="海岸跟拍")
        subject = Conversation(title="角色主體參考")
        style = Conversation(title="膠片風格")
        db.add_all([coast, subject, style])
        db.flush()
        db.add_all(
            [
                CommandRecord(
                    conversation_id=coast.id,
                    prompt="黃昏海岸低角度跟拍，暖色長陰影，電影感顆粒。",
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    quality="1080p",
                    gen_type="text_to_video",
                    status="done",
                    estimated_tokens=11200,
                    estimated_cost_usd="0.448",
                    estimated_cost_ntd="14.34",
                    elapsed_seconds="142.6",
                ),
                CommandRecord(
                    conversation_id=coast.id,
                    prompt="同一條海岸改為薄霧清晨，冷色調，遠景無人。",
                    duration_seconds=8,
                    aspect_ratio="16:9",
                    quality="720p",
                    gen_type="text_to_video",
                    status="done",
                    estimated_tokens=8000,
                    estimated_cost_usd="0.32",
                    estimated_cost_ntd="10.24",
                    elapsed_seconds="118.2",
                ),
                CommandRecord(
                    conversation_id=subject.id,
                    prompt="以參考圖鎖定同一位旅人，走入夜市燈籠下。",
                    duration_seconds=8,
                    aspect_ratio="9:16",
                    quality="1080p",
                    gen_type="ref_subject",
                    status="error",
                    error_message="RESOURCE_EXHAUSTED",
                    elapsed_seconds="9.4",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()


def main() -> None:
    seed_demo()

    import tkinter as tk

    try:
        from tkinterdnd2 import TkinterDnD

        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()

    app = VeoDesktopApp(root)
    root.geometry("1680x940+40+40")
    root.update_idletasks()

    def run_shots() -> None:
        try:
            if app._conversation_ids:
                app.conv_list.selection_clear(0, tk.END)
                app.conv_list.selection_set(0)
                app.on_conversation_select()
            app.set_status("準備就緒 — 示範資料，未連線真實 API")
            root.update()
            capture_widget(root, OUT_DIR / "demo-desktop-dark.png")

            app.theme = "light"
            app._apply_theme()
            root.update()
            capture_widget(root, OUT_DIR / "demo-desktop-light.png")

            app.theme = "dark"
            app._apply_theme()
            app.open_settings_page()
            root.update()
            capture_widget(app.settings_window, OUT_DIR / "demo-settings.png")
            app.settings_window.destroy()

            app.open_usage_page()
            root.update()
            capture_widget(app.usage_window, OUT_DIR / "demo-usage.png")
        finally:
            root.destroy()

    root.after(700, run_shots)
    root.mainloop()


if __name__ == "__main__":
    main()
