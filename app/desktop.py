import base64
import json
import threading
import tkinter as tk
import tkinter.font as tkfont
import mimetypes
import os
import sys
from pathlib import Path
from tkinter import filedialog, messagebox
import webbrowser

from .config import load_config, mask_key, save_config
from .db import Base, SessionLocal, engine
from .models import CommandRecord, Conversation
from .paths import ASSETS_DIR, VIDEOS_DIR
from .services.discord_bot import run_bot_in_thread
from .services.storage import save_uploaded_image
from .services.usage_logger import log_usage
from .services.veo_client import GEN_TYPE_LABELS, GEN_TYPES, VeoClientError, estimate_cost, generate_video

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False
    DND_FILES = None
    TkinterDnD = None


class VeoDesktopApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Veo Local Studio")
        self.root.geometry("1600x900")
        self.root.minsize(980, 620)
        self.root.option_add("*Font", ("Microsoft JhengHei", 10))

        Base.metadata.create_all(bind=engine)

        self.theme = "light"
        self.selected_images: list[Path] = []
        self.source_command_id: int | None = None
        self.active_conversation_id: int | None = None
        self.current_commands: list[CommandRecord] = []
        self.discord_tutorial_window: tk.Toplevel | None = None
        self.gemini_tutorial_window: tk.Toplevel | None = None
        self.usage_guide_window: tk.Toplevel | None = None
        self.settings_window: tk.Toplevel | None = None
        self.usage_window: tk.Toplevel | None = None
        self.logo_image: tk.PhotoImage | None = None
        self.icon_ico_path: Path | None = None
        self.palette: dict[str, str] = {}
        self.dnd_available = bool(DND_AVAILABLE)
        self._base_tk_scaling = float(self.root.tk.call("tk", "scaling"))
        self._zoom_factor = 1.0

        self.api_base_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.model_var = tk.StringVar(value="veo-3.1-generate-preview")
        self.backup_api_base_var = tk.StringVar()
        self.backup_api_key_var = tk.StringVar()
        self.backup_model_var = tk.StringVar(value="veo-3.1-generate-preview")
        self.max_images_var = tk.StringVar(value="8")
        self.discord_enabled_var = tk.BooleanVar(value=False)
        self.discord_token_var = tk.StringVar()
        self.discord_sync_guild_var = tk.StringVar()
        self.cost_per_second_var = tk.StringVar(value="0.04")
        self.mult_720_var = tk.StringVar(value="1.0")
        self.mult_1080_var = tk.StringVar(value="1.4")
        self.mult_2k_var = tk.StringVar(value="2.0")
        self.mult_4k_var = tk.StringVar(value="3.2")

        self._load_logo_assets()
        self._register_window_controls(self.root)
        self._build_ui()
        self._load_config_into_form()
        self._load_ui_state()
        self._apply_theme()
        self._load_conversations()
        self._start_discord_if_enabled()
        self.root.protocol("WM_DELETE_WINDOW", self.on_app_close)

    def _load_logo_assets(self):
        icon_path = ASSETS_DIR / "app.ico"
        logo_path = ASSETS_DIR / "logo.png"
        if icon_path.exists():
            self.icon_ico_path = icon_path
            try:
                self.root.iconbitmap(default=str(icon_path))
            except Exception:
                pass
        try:
            if logo_path.exists():
                self.logo_image = tk.PhotoImage(file=str(logo_path))
        except Exception:
            self.logo_image = None

    @staticmethod
    def _google_default_base() -> str:
        return "https://generativelanguage.googleapis.com/v1beta"

    @staticmethod
    def _google_default_model() -> str:
        return "veo-3.1-generate-preview"

    def _apply_window_icon(self, window: tk.Toplevel):
        if self.icon_ico_path and self.icon_ico_path.exists():
            try:
                window.iconbitmap(default=str(self.icon_ico_path))
            except Exception:
                pass
        if self.logo_image:
            try:
                window.iconphoto(True, self.logo_image)
            except Exception:
                pass

    def _register_window_controls(self, window: tk.Misc):
        window.bind("<Control-MouseWheel>", self._on_zoom_mousewheel)
        window.bind("<Control-plus>", lambda _e: self._zoom_by(1.08))
        window.bind("<Control-minus>", lambda _e: self._zoom_by(0.92))
        window.bind("<Control-0>", lambda _e: self._reset_zoom())

    def _on_zoom_mousewheel(self, event):
        self._zoom_by(1.06 if event.delta > 0 else 0.94)

    def _zoom_by(self, factor: float):
        self._zoom_factor = max(0.65, min(1.8, self._zoom_factor * factor))
        self.root.tk.call("tk", "scaling", self._base_tk_scaling * self._zoom_factor)
        # Keep named fonts readable while scaling globally.
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                f = tkfont.nametofont(name)
                f.configure(size=max(8, int(10 * self._zoom_factor)))
            except Exception:
                pass

    def _reset_zoom(self):
        self._zoom_factor = 1.0
        self.root.tk.call("tk", "scaling", self._base_tk_scaling)

    def _bind_canvas_wheel(self, canvas: tk.Canvas):
        def _on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

    def _build_ui(self):
        self.main = tk.Frame(self.root)
        self.main.pack(fill="both", expand=True)

        self.left = tk.Frame(self.main, width=260)
        self.center = tk.Frame(self.main)
        self.right = tk.Frame(self.main, width=320)
        self.left.pack(side="left", fill="y")
        self.left.pack_propagate(False)
        self.center.pack(side="left", fill="both", expand=True)
        self.right.pack(side="left", fill="y")
        self.right.pack_propagate(False)

        left_header = tk.Frame(self.left)
        left_header.pack(fill="x", padx=14, pady=(16, 8))
        if self.logo_image:
            tk.Label(left_header, image=self.logo_image).pack(side="left", padx=(0, 10))
        tk.Label(left_header, text="對話", font=("Microsoft JhengHei", 12, "bold")).pack(side="left")
        self.new_conv_btn = tk.Button(self.left, text="+ 新對話", command=self.create_conversation)
        self.new_conv_btn.pack(padx=14, pady=6, fill="x")
        self.conv_list = tk.Listbox(self.left, exportselection=False)
        self.conv_list.pack(padx=14, pady=6, fill="both", expand=True)
        self.conv_list.bind("<<ListboxSelect>>", self.on_conversation_select)

        top_actions = tk.Frame(self.center)
        top_actions.pack(fill="x", padx=20, pady=(16, 8))
        title_row = tk.Frame(top_actions)
        title_row.pack(fill="x")
        self.current_conv_label = tk.Label(title_row, text="尚未選擇對話", font=("Microsoft JhengHei", 13, "bold"))
        self.current_conv_label.pack(side="left")
        button_row = tk.Frame(top_actions)
        button_row.pack(fill="x", pady=(8, 0))
        self.toggle_theme_btn = tk.Button(button_row, text="切換主題", command=self.toggle_theme)
        self.restart_btn = tk.Button(button_row, text="重啟應用", command=self.restart_application)
        self.discord_tutorial_btn = tk.Button(button_row, text="Discord 教學", command=self.open_discord_tutorial)
        self.open_guide_btn = tk.Button(button_row, text="使用教學", command=self.open_usage_guide)
        self.open_gemini_tutorial_btn = tk.Button(button_row, text="Gemini API 教學", command=self.open_gemini_tutorial)
        self.open_usage_btn = tk.Button(button_row, text="用量與花費", command=self.open_usage_page)
        self.open_settings_btn = tk.Button(button_row, text="設定頁面", command=self.open_settings_page)
        for btn in (
            self.toggle_theme_btn,
            self.restart_btn,
            self.discord_tutorial_btn,
            self.open_guide_btn,
            self.open_gemini_tutorial_btn,
            self.open_usage_btn,
            self.open_settings_btn,
        ):
            btn.pack(side="left", padx=(0, 6))

        cmd_box = tk.LabelFrame(self.center, text="命令輸入")
        cmd_box.pack(fill="both", expand=True, padx=20, pady=(12, 16))
        self.prompt_text = tk.Text(cmd_box, height=10)
        self.prompt_text.pack(fill="x", padx=8, pady=6)

        image_row = tk.Frame(cmd_box)
        image_row.pack(fill="x", padx=8, pady=6)
        self.pick_images_btn = tk.Button(image_row, text="選擇素材", command=self.pick_images)
        self.pick_images_btn.pack(side="left")
        self.clear_images_btn = tk.Button(image_row, text="清空素材", command=self.clear_images)
        self.clear_images_btn.pack(side="left", padx=6)
        self.image_info_label = tk.Label(image_row, text="目前 0 個素材")
        self.image_info_label.pack(side="left", padx=8)
        if not self.dnd_available:
            tk.Label(image_row, text="（拖放未啟用，請使用選擇素材）").pack(side="left", padx=8)

        self.drop_zone = tk.Label(
            cmd_box,
            text="將圖片或其他素材拖放到此區域（可多檔）",
            height=3,
            justify="center",
        )
        self.drop_zone.pack(fill="x", padx=8, pady=(2, 8))
        if self.dnd_available:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self.on_files_dropped)

        asset_sort_row = tk.Frame(cmd_box)
        asset_sort_row.pack(fill="both", padx=8, pady=(0, 8))
        self.asset_order_list = tk.Listbox(asset_sort_row, height=6, exportselection=False)
        self.asset_order_list.pack(side="left", fill="both", expand=True)
        sort_actions = tk.Frame(asset_sort_row)
        sort_actions.pack(side="left", padx=(8, 0), fill="y")
        self.asset_up_btn = tk.Button(sort_actions, text="上移", command=self.move_asset_up)
        self.asset_up_btn.pack(fill="x", pady=(0, 6))
        self.asset_down_btn = tk.Button(sort_actions, text="下移", command=self.move_asset_down)
        self.asset_down_btn.pack(fill="x")
        tk.Label(
            cmd_box,
            text="可在此排序素材；指令中請用 @圖1 @圖2 ... 對應清單順序。",
        ).pack(anchor="w", padx=8, pady=(0, 6))

        option_row = tk.Frame(cmd_box)
        option_row.pack(fill="x", padx=8, pady=6)
        self.duration_var = tk.StringVar(value="8")
        self.aspect_var = tk.StringVar(value="16:9")
        self.quality_var = tk.StringVar(value="1080p")
        self.gen_type_var = tk.StringVar(value="text_to_video")
        self._add_option(option_row, "時間(秒)", self.duration_var, ["4", "6", "8", "12"])
        self._add_option(option_row, "畫面比例", self.aspect_var, ["16:9", "9:16", "1:1", "4:3"])
        self._add_option(option_row, "畫質", self.quality_var, ["720p", "1080p", "2k", "4k"])

        # 生成類型下拉選單（含所有 7 種類型，顯示中文標籤）
        gen_type_row = tk.Frame(cmd_box)
        gen_type_row.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(gen_type_row, text="生成類型").pack(side="left", padx=(0, 6))
        gen_type_display_values = [GEN_TYPE_LABELS[gt] for gt in GEN_TYPES]
        self._gen_type_display_var = tk.StringVar(
            value=GEN_TYPE_LABELS.get("text_to_video", "文字轉影片")
        )
        gen_type_menu = tk.OptionMenu(
            gen_type_row, self._gen_type_display_var, *gen_type_display_values,
            command=self._on_gen_type_changed,
        )
        gen_type_menu.pack(side="left", fill="x", expand=True)
        self._gen_type_menu = gen_type_menu
        self.cost_label = tk.Label(gen_type_row, text="")
        self.cost_label.pack(side="left", padx=(10, 0))
        # 繫結選項變化時更新費用估算
        self.duration_var.trace_add("write", lambda *_: self._update_cost_label())
        self.quality_var.trace_add("write",  lambda *_: self._update_cost_label())
        self.gen_type_var.trace_add("write",  lambda *_: self._update_cost_label())
        self._update_cost_label()

        self.generate_btn = tk.Button(cmd_box, text="生成影片", command=self.generate_video_async)
        self.generate_btn.pack(padx=8, pady=8, anchor="e")
        self.status_label = tk.Label(cmd_box, text="準備就緒")
        self.status_label.pack(padx=8, pady=(0, 8), anchor="w")

        tk.Label(self.right, text="歷史命令（可載入修改重跑）", font=("Microsoft JhengHei", 11, "bold")).pack(
            padx=14, pady=(16, 8), anchor="w"
        )
        self.history_list = tk.Listbox(self.right, exportselection=False)
        self.history_list.pack(padx=14, pady=6, fill="both", expand=True)
        self.load_history_btn = tk.Button(self.right, text="載入選取命令", command=self.load_selected_history)
        self.load_history_btn.pack(padx=14, pady=6, fill="x")
        self.open_outputs_btn = tk.Button(self.right, text="打開輸出資料夾", command=self.open_outputs_folder)
        self.open_outputs_btn.pack(padx=14, pady=(0, 14), fill="x")

    def _on_gen_type_changed(self, display_label: str):
        """將顯示用中文標籤反查回英文 key。"""
        for gt in GEN_TYPES:
            if GEN_TYPE_LABELS[gt] == display_label:
                self.gen_type_var.set(gt)
                break
        self._update_cost_label()

    def _update_cost_label(self):
        try:
            duration = int(self.duration_var.get() or "8")
            quality  = self.quality_var.get() or "1080p"
            gt       = self.gen_type_var.get() or "text_to_video"
            cost     = estimate_cost(duration, quality, gt)
            text = f"預估：{cost['tokens']:,} Token ≈ NT${cost['ntd']:.2f}"
        except Exception:
            text = ""
        if hasattr(self, "cost_label") and self.cost_label.winfo_exists():
            self.cost_label.config(text=text)

    def _add_entry(self, parent, label, var, show=None):
        tk.Label(parent, text=label).pack(padx=8, pady=(6, 2), anchor="w")
        entry = tk.Entry(parent, textvariable=var, show=show)
        entry.pack(padx=8, pady=(0, 4), fill="x")
        return entry

    def _add_option(self, parent, label, var, options):
        box = tk.Frame(parent)
        box.pack(side="left", padx=6)
        tk.Label(box, text=label).pack(anchor="w")
        menu = tk.OptionMenu(box, var, *options)
        menu.pack(fill="x")

    def _apply_theme(self):
        if self.theme == "dark":
            palette = {
                "bg": "#14161a",
                "panel": "#1e2127",
                "panel_alt": "#242836",
                "text": "#edf0f7",
                "subtext": "#b3bccf",
                "input": "#2b3040",
                "accent": "#5865f2",
                "accent_active": "#4c58dd",
            }
        else:
            palette = {
                "bg": "#f5f5f7",
                "panel": "#ffffff",
                "panel_alt": "#fbfbfd",
                "text": "#1d1d1f",
                "subtext": "#6e6e73",
                "input": "#f2f2f7",
                "accent": "#0071e3",
                "accent_active": "#0062c4",
            }

        self.palette = palette
        self.root.configure(bg=palette["bg"])
        self.main.configure(bg=palette["bg"])
        self.left.configure(bg=palette["panel_alt"])
        self.center.configure(bg=palette["bg"])
        self.right.configure(bg=palette["panel_alt"])
        self._paint_widget_tree(self.root, palette)
        self.status_label.configure(fg=palette["subtext"])
        self._apply_settings_theme()
        self._apply_usage_theme()
        self._apply_usage_guide_theme()
        self._apply_gemini_tutorial_theme()
        self._apply_tutorial_theme()

    def _paint_widget_tree(self, widget, palette):
        for child in widget.winfo_children():
            if isinstance(child, tk.Frame):
                child.configure(bg=palette["panel"])
            elif isinstance(child, tk.LabelFrame):
                child.configure(bg=palette["panel"], fg=palette["text"], bd=1, relief="solid")
            elif isinstance(child, tk.Label):
                child.configure(bg=palette["panel"], fg=palette["text"])
            elif isinstance(child, tk.Text):
                child.configure(
                    bg=palette["input"],
                    fg=palette["text"],
                    insertbackground=palette["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=palette["input"],
                    highlightcolor=palette["accent"],
                    padx=10,
                    pady=8,
                )
            elif isinstance(child, tk.Entry):
                child.configure(
                    bg=palette["input"],
                    fg=palette["text"],
                    insertbackground=palette["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=palette["input"],
                    highlightcolor=palette["accent"],
                )
            elif isinstance(child, tk.Listbox):
                child.configure(
                    bg=palette["input"],
                    fg=palette["text"],
                    selectbackground=palette["accent"],
                    selectforeground="#ffffff",
                    relief="flat",
                    bd=0,
                    highlightthickness=0,
                )
            elif isinstance(child, tk.Button):
                is_primary = child is self.generate_btn or child is self.new_conv_btn
                child.configure(
                    bg=palette["accent"] if is_primary else palette["input"],
                    fg="#ffffff" if is_primary else palette["text"],
                    activebackground=palette["accent_active"] if is_primary else palette["panel_alt"],
                    activeforeground="#ffffff" if is_primary else palette["text"],
                    relief="flat",
                    bd=0,
                    padx=12,
                    pady=8,
                    highlightthickness=1,
                    highlightbackground=palette["bg"],
                    highlightcolor=palette["accent"],
                    cursor="hand2",
                )
            elif isinstance(child, tk.OptionMenu):
                child.configure(
                    bg=palette["input"],
                    fg=palette["text"],
                    activebackground=palette["panel_alt"],
                    relief="flat",
                    bd=0,
                    highlightthickness=0,
                )
                child["menu"].configure(
                    bg=palette["input"],
                    fg=palette["text"],
                    activebackground=palette["accent"],
                    activeforeground="#ffffff",
                )
            elif isinstance(child, tk.Checkbutton):
                child.configure(bg=palette["panel"], fg=palette["text"], selectcolor=palette["input"])
            self._paint_widget_tree(child, palette)

    def toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self._apply_theme()
        self._save_ui_state()

    def set_status(self, text):
        self.status_label.config(text=text)

    def _load_config_into_form(self):
        cfg = load_config()
        default_google_base = self._google_default_base()
        default_google_model = self._google_default_model()
        self.api_base_var.set(cfg.get("veo_api_base", "") or default_google_base)
        self.api_key_var.set(cfg.get("veo_api_key", ""))
        self.model_var.set(cfg.get("veo_model", "") or default_google_model)
        backup_apis = cfg.get("backup_apis", [])
        first_backup = backup_apis[0] if isinstance(backup_apis, list) and backup_apis else {}
        self.backup_api_base_var.set(first_backup.get("api_base", ""))
        self.backup_api_key_var.set(first_backup.get("api_key", ""))
        self.backup_model_var.set(first_backup.get("model", "") or default_google_model)
        self.max_images_var.set(str(cfg.get("max_image_inputs", 8)))
        self.discord_enabled_var.set(bool(cfg.get("discord_enabled", False)))
        self.discord_token_var.set(cfg.get("discord_bot_token", ""))
        self.discord_sync_guild_var.set(
            cfg.get("discord_sync_guild_ids") or cfg.get("discord_sync_guild_id", "")
        )
        self.cost_per_second_var.set(str(cfg.get("cost_per_second_usd", "0.04")))
        quality_multipliers = cfg.get("quality_multipliers", {})
        self.mult_720_var.set(str(quality_multipliers.get("720p", "1.0")))
        self.mult_1080_var.set(str(quality_multipliers.get("1080p", "1.4")))
        self.mult_2k_var.set(str(quality_multipliers.get("2k", "2.0")))
        self.mult_4k_var.set(str(quality_multipliers.get("4k", "3.2")))
        theme = cfg.get("ui_theme", "light")
        self.theme = theme if theme in ("light", "dark") else "light"
        if hasattr(self, "masked_key_label") and self.masked_key_label.winfo_exists():
            self.masked_key_label.config(text=f"目前 API Key: {mask_key(cfg.get('veo_api_key', '')) or '未設定'}")
        if hasattr(self, "backup_masked_key_label") and self.backup_masked_key_label.winfo_exists():
            self.backup_masked_key_label.config(
                text=f"目前備用 API Key: {mask_key(first_backup.get('api_key', '')) or '未設定'}"
            )

    def _load_ui_state(self):
        cfg = load_config()
        ui_state = cfg.get("ui_state", {}) if isinstance(cfg.get("ui_state"), dict) else {}
        self._preferred_conversation_id = ui_state.get("active_conversation_id")
        prompt = ui_state.get("prompt_draft", "")
        if prompt:
            self.prompt_text.delete("1.0", tk.END)
            self.prompt_text.insert("1.0", prompt)
        self.duration_var.set(str(ui_state.get("duration_seconds", self.duration_var.get())))
        self.aspect_var.set(str(ui_state.get("aspect_ratio", self.aspect_var.get())))
        self.quality_var.set(str(ui_state.get("quality", self.quality_var.get())))
        saved_gt = ui_state.get("gen_type", "text_to_video")
        if saved_gt in GEN_TYPES:
            self.gen_type_var.set(saved_gt)
            self._gen_type_display_var.set(GEN_TYPE_LABELS.get(saved_gt, "文字轉影片"))
        restored_paths = []
        for p in ui_state.get("selected_assets", []) if isinstance(ui_state.get("selected_assets"), list) else []:
            pp = Path(p)
            if pp.exists() and pp.is_file():
                restored_paths.append(pp)
        self.selected_images = restored_paths
        self._refresh_asset_count()

    def _save_ui_state(self):
        prompt = self.prompt_text.get("1.0", tk.END).strip()
        payload = {
            "ui_theme": self.theme,
            "ui_state": {
                "active_conversation_id": self.active_conversation_id,
                "prompt_draft": prompt,
                "duration_seconds": self.duration_var.get(),
                "aspect_ratio": self.aspect_var.get(),
                "quality": self.quality_var.get(),
                "gen_type": self.gen_type_var.get(),
                "selected_assets": [str(p) for p in self.selected_images],
            },
        }
        save_config(payload)

    def save_config_from_form(self):
        current = load_config()
        try:
            max_inputs = int(self.max_images_var.get().strip() or "8")
            cost_per_second = float(self.cost_per_second_var.get().strip() or "0.04")
            mult_720 = float(self.mult_720_var.get().strip() or "1.0")
            mult_1080 = float(self.mult_1080_var.get().strip() or "1.4")
            mult_2k = float(self.mult_2k_var.get().strip() or "2.0")
            mult_4k = float(self.mult_4k_var.get().strip() or "3.2")
        except ValueError:
            messagebox.showerror("設定錯誤", "請確認數字欄位格式正確（Max images / 費率 / 乘數）。")
            return
        incoming = {
            "veo_api_base": self.api_base_var.get().strip(),
            "veo_api_key": self.api_key_var.get().strip() or current.get("veo_api_key", ""),
            "veo_model": self.model_var.get().strip() or "veo-3.1-generate-preview",
            "max_image_inputs": max_inputs,
            "discord_enabled": bool(self.discord_enabled_var.get()),
            "discord_bot_token": self.discord_token_var.get().strip()
            or current.get("discord_bot_token", ""),
            "discord_sync_guild_ids": self.discord_sync_guild_var.get().strip(),
            "cost_per_second_usd": cost_per_second,
            "quality_multipliers": {
                "720p": mult_720,
                "1080p": mult_1080,
                "2k": mult_2k,
                "4k": mult_4k,
            },
        }
        backup_api_base = self.backup_api_base_var.get().strip()
        backup_api_key = self.backup_api_key_var.get().strip()
        backup_model = self.backup_model_var.get().strip() or "veo-3.1-generate-preview"
        existing_backup = {}
        if isinstance(current.get("backup_apis"), list) and current["backup_apis"]:
            existing_backup = current["backup_apis"][0]
        if backup_api_base:
            incoming["backup_apis"] = [
                {
                    "api_base": backup_api_base,
                    "api_key": backup_api_key or existing_backup.get("api_key", ""),
                    "model": backup_model,
                }
            ]
        else:
            incoming["backup_apis"] = []
        save_config(incoming)
        self._load_config_into_form()
        self._save_ui_state()
        messagebox.showinfo("設定", "設定已儲存。Discord 切換需重啟應用程式。")

    def _start_discord_if_enabled(self):
        cfg = load_config()
        if cfg.get("discord_enabled") and cfg.get("discord_bot_token"):
            run_bot_in_thread(cfg["discord_bot_token"], SessionLocal)

    def _load_conversations(self):
        db = SessionLocal()
        try:
            items = db.query(Conversation).order_by(Conversation.updated_at.desc()).all()
        finally:
            db.close()
        self.conv_list.delete(0, tk.END)
        self._conversation_ids: list[int] = []
        for c in items:
            self._conversation_ids.append(c.id)
            self.conv_list.insert(tk.END, c.title)
        if items:
            selected_idx = 0
            preferred = getattr(self, "_preferred_conversation_id", None)
            if preferred in self._conversation_ids:
                selected_idx = self._conversation_ids.index(preferred)
            self.conv_list.selection_set(selected_idx)
            self.active_conversation_id = self._conversation_ids[selected_idx]
            self.current_conv_label.config(text=items[selected_idx].title)
            self._load_history(self.active_conversation_id)

    def create_conversation(self):
        db = SessionLocal()
        try:
            row = Conversation(title=f"對話 {len(self._conversation_ids) + 1}")
            db.add(row)
            db.commit()
        finally:
            db.close()
        self._load_conversations()

    def on_conversation_select(self, _event=None):
        if not self.conv_list.curselection():
            return
        idx = self.conv_list.curselection()[0]
        conv_id = self._conversation_ids[idx]
        self.active_conversation_id = conv_id

        db = SessionLocal()
        try:
            conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
            if conv:
                self.current_conv_label.config(text=conv.title)
        finally:
            db.close()
        self._load_history(conv_id)
        self._save_ui_state()

    def _load_history(self, conversation_id: int):
        db = SessionLocal()
        try:
            rows = (
                db.query(CommandRecord)
                .filter(CommandRecord.conversation_id == conversation_id)
                .order_by(CommandRecord.created_at.desc())
                .all()
            )
        finally:
            db.close()
        self.current_commands = rows
        self.history_list.delete(0, tk.END)
        for r in rows:
            self.history_list.insert(
                tk.END,
                f"#{r.id} [{r.status}] {r.duration_seconds}s {r.aspect_ratio} {r.quality} | {r.prompt[:48]}",
            )

    def _parse_dropped_files(self, data: str) -> list[Path]:
        paths: list[str] = []
        buffer = ""
        in_brace = False
        for ch in data:
            if ch == "{":
                in_brace = True
                buffer = ""
                continue
            if ch == "}":
                in_brace = False
                if buffer:
                    paths.append(buffer)
                buffer = ""
                continue
            if ch == " " and not in_brace:
                if buffer:
                    paths.append(buffer)
                    buffer = ""
                continue
            buffer += ch
        if buffer:
            paths.append(buffer)

        files: list[Path] = []
        for raw in paths:
            p = Path(raw.strip().strip('"'))
            if p.exists() and p.is_file():
                files.append(p)
        return files

    def _refresh_asset_count(self):
        self.image_info_label.config(text=f"目前 {len(self.selected_images)} 個素材")
        self.asset_order_list.delete(0, tk.END)
        for idx, p in enumerate(self.selected_images, start=1):
            self.asset_order_list.insert(tk.END, f"@圖{idx} -> {p.name}")

    def _append_assets(self, files: list[Path]):
        existing = {str(p).lower() for p in self.selected_images}
        appended = 0
        for p in files:
            k = str(p).lower()
            if k not in existing:
                self.selected_images.append(p)
                existing.add(k)
                appended += 1
        self._refresh_asset_count()
        if appended > 0:
            self.set_status(f"已加入 {appended} 個素材。")
            self._save_ui_state()

    def move_asset_up(self):
        if not self.asset_order_list.curselection():
            return
        idx = self.asset_order_list.curselection()[0]
        if idx <= 0:
            return
        self.selected_images[idx - 1], self.selected_images[idx] = self.selected_images[idx], self.selected_images[idx - 1]
        self._refresh_asset_count()
        self.asset_order_list.selection_set(idx - 1)
        self._save_ui_state()

    def move_asset_down(self):
        if not self.asset_order_list.curselection():
            return
        idx = self.asset_order_list.curselection()[0]
        if idx >= len(self.selected_images) - 1:
            return
        self.selected_images[idx + 1], self.selected_images[idx] = self.selected_images[idx], self.selected_images[idx + 1]
        self._refresh_asset_count()
        self.asset_order_list.selection_set(idx + 1)
        self._save_ui_state()

    def on_files_dropped(self, event):
        files = self._parse_dropped_files(event.data or "")
        if files:
            self._append_assets(files)

    def pick_images(self):
        files = filedialog.askopenfilenames(
            title="選擇輸入素材",
            filetypes=[
                ("All Files", "*.*"),
                ("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                ("Video", "*.mp4 *.mov *.mkv *.webm"),
                ("Audio", "*.wav *.mp3 *.m4a"),
                ("Documents", "*.txt *.pdf *.json *.md"),
            ],
        )
        if not files:
            return
        self._append_assets([Path(x) for x in files])

    def clear_images(self):
        self.selected_images = []
        self._refresh_asset_count()
        self._save_ui_state()

    def load_selected_history(self):
        if not self.history_list.curselection():
            messagebox.showwarning("提醒", "請先選取右側歷史命令。")
            return
        cmd = self.current_commands[self.history_list.curselection()[0]]
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", cmd.prompt)
        self.duration_var.set(str(cmd.duration_seconds))
        self.aspect_var.set(cmd.aspect_ratio)
        self.quality_var.set(cmd.quality)
        gt = getattr(cmd, "gen_type", "text_to_video") or "text_to_video"
        if gt in GEN_TYPES:
            self.gen_type_var.set(gt)
            self._gen_type_display_var.set(GEN_TYPE_LABELS.get(gt, "文字轉影片"))
        self.source_command_id = cmd.id
        self.set_status(f"已載入命令 #{cmd.id}，可修改後再次生成。")

    def generate_video_async(self):
        threading.Thread(target=self._generate_video, daemon=True).start()

    def _generate_video(self):
        if not self.active_conversation_id:
            self.root.after(0, lambda: messagebox.showwarning("提醒", "請先建立或選擇對話。"))
            return

        prompt = self.prompt_text.get("1.0", tk.END).strip()
        if not prompt:
            self.root.after(0, lambda: messagebox.showwarning("提醒", "請先輸入 prompt。"))
            return

        cfg = load_config()
        max_inputs = int(cfg.get("max_image_inputs", 8))
        if len(self.selected_images) > max_inputs:
            self.root.after(0, lambda: messagebox.showwarning("提醒", f"素材不可超過 {max_inputs} 個"))
            return

        gen_type  = self.gen_type_var.get() or "text_to_video"
        duration  = int(self.duration_var.get())
        aspect    = self.aspect_var.get()
        quality   = self.quality_var.get()

        self.root.after(0, lambda: self.set_status("生成中，請稍候..."))

        import time as _time
        t0 = _time.time()

        db = SessionLocal()
        try:
            image_payloads = []
            image_paths = []
            for idx, p in enumerate(self.selected_images, start=1):
                raw = p.read_bytes()
                stored = save_uploaded_image(raw, p.suffix or ".png")
                image_paths.append(str(stored))
                guessed_mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
                image_payloads.append(
                    {
                        "name": f"@圖{idx}",
                        "original_name": p.name,
                        "mime_type": guessed_mime,
                        "data_base64": base64.b64encode(raw).decode("ascii"),
                    }
                )

            cmd = CommandRecord(
                conversation_id=self.active_conversation_id,
                prompt=prompt,
                image_paths=json.dumps(image_paths, ensure_ascii=False),
                duration_seconds=duration,
                aspect_ratio=aspect,
                quality=quality,
                gen_type=gen_type,
                source_command_id=self.source_command_id,
                status="running",
            )
            db.add(cmd)
            db.commit()
            db.refresh(cmd)

            try:
                result = generate_video(
                    prompt=prompt,
                    images=image_payloads,
                    duration_seconds=duration,
                    aspect_ratio=aspect,
                    quality=quality,
                    gen_type=gen_type,
                )
                elapsed = _time.time() - t0
                cost = result.get("cost", estimate_cost(duration, quality, gen_type))
                cmd.status            = "done"
                cmd.provider_job_id   = result.get("provider_job_id")
                cmd.output_video_path = result["video_web_path"]
                cmd.raw_response      = json.dumps(result["raw_response"], ensure_ascii=False)
                cmd.estimated_tokens  = cost["tokens"]
                cmd.estimated_cost_usd = str(cost["usd"])
                cmd.estimated_cost_ntd = str(cost["ntd"])
                cmd.elapsed_seconds   = str(round(elapsed, 2))
                status_text = (
                    f"✅ 生成完成 | {GEN_TYPE_LABELS.get(gen_type, gen_type)} | "
                    f"{int(elapsed)} 秒 | "
                    f"{cost['tokens']:,} Token ≈ NT${cost['ntd']:.2f}"
                )
                log_usage(
                    source="desktop",
                    conversation_id=cmd.conversation_id,
                    command_id=cmd.id,
                    gen_type=gen_type,
                    prompt=prompt,
                    duration_seconds=duration,
                    aspect_ratio=aspect,
                    quality=quality,
                    estimated_tokens=cost["tokens"],
                    estimated_cost_usd=cost["usd"],
                    estimated_cost_ntd=cost["ntd"],
                    elapsed_seconds=elapsed,
                    status="done",
                    video_path=result["video_path"],
                    provider=result.get("used_provider", ""),
                )
            except VeoClientError as exc:
                elapsed = _time.time() - t0
                cmd.status = "error"
                cmd.error_message = str(exc)
                cmd.elapsed_seconds = str(round(elapsed, 2))
                status_text = f"❌ 生成失敗：{exc}"
                log_usage(
                    source="desktop",
                    conversation_id=cmd.conversation_id,
                    command_id=cmd.id,
                    gen_type=gen_type,
                    prompt=prompt,
                    duration_seconds=duration,
                    aspect_ratio=aspect,
                    quality=quality,
                    elapsed_seconds=elapsed,
                    status="error",
                    error_message=str(exc),
                )
            except Exception as exc:
                elapsed = _time.time() - t0
                cmd.status = "error"
                cmd.error_message = f"系統錯誤：{exc}"
                cmd.elapsed_seconds = str(round(elapsed, 2))
                status_text = f"⚠️ 系統錯誤：{exc}"
                log_usage(
                    source="desktop",
                    conversation_id=cmd.conversation_id,
                    command_id=cmd.id,
                    gen_type=gen_type,
                    prompt=prompt,
                    duration_seconds=duration,
                    aspect_ratio=aspect,
                    quality=quality,
                    elapsed_seconds=elapsed,
                    status="error",
                    error_message=str(exc),
                )

            db.add(cmd)
            db.commit()
        finally:
            db.close()

        self.source_command_id = None
        self.root.after(0, lambda: self.set_status(status_text))
        self.root.after(0, lambda: self._load_history(self.active_conversation_id))

    def open_outputs_folder(self):
        out = VIDEOS_DIR
        out.mkdir(parents=True, exist_ok=True)
        try:
            import os

            os.startfile(out)
        except Exception as exc:
            messagebox.showerror("錯誤", f"無法開啟資料夾：{exc}")

    def open_settings_page(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.destroy()
            self.settings_window = None

        win = tk.Toplevel(self.root)
        win.title("設定頁面 - API / 模型 / Discord")
        win.geometry("780x700")
        win.minsize(560, 420)
        self._apply_window_icon(win)
        self._register_window_controls(win)
        self.settings_window = win

        shell = tk.Frame(win, padx=12, pady=12)
        shell.pack(fill="both", expand=True)

        viewport = tk.Frame(shell)
        viewport.pack(fill="both", expand=True)
        canvas = tk.Canvas(viewport, highlightthickness=0)
        scrollbar = tk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas)
        content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._bind_canvas_wheel(canvas)

        tk.Label(content, text="模型與 API 設定", font=("Microsoft JhengHei", 15, "bold")).pack(anchor="w")
        tk.Label(
            content,
            text="主頁面僅保留命令與輸出選項；本頁集中管理 API/模型/DC Bot/成本參數。",
        ).pack(anchor="w", pady=(2, 10))

        card = tk.LabelFrame(content, text="Veo API / 模型")
        card.pack(fill="x", pady=(0, 10))
        self._add_entry(card, "API Base URL", self.api_base_var)
        self._add_entry(card, "API Key（留空不覆蓋）", self.api_key_var, show="*")
        self._add_entry(card, "模型名稱", self.model_var)
        self._add_entry(card, "最大圖片輸入數量", self.max_images_var)
        self.masked_key_label = tk.Label(card, text="")
        self.masked_key_label.pack(padx=8, pady=(0, 8), anchor="w")

        backup_card = tk.LabelFrame(content, text="備用 AI API（主 API 失敗時自動切換）")
        backup_card.pack(fill="x", pady=(0, 10))
        self._add_entry(backup_card, "備用 API Base URL", self.backup_api_base_var)
        self._add_entry(backup_card, "備用 API Key（留空不覆蓋）", self.backup_api_key_var, show="*")
        self._add_entry(backup_card, "備用模型名稱", self.backup_model_var)
        self.backup_masked_key_label = tk.Label(backup_card, text="")
        self.backup_masked_key_label.pack(padx=8, pady=(0, 8), anchor="w")

        dc_card = tk.LabelFrame(content, text="Discord Bot")
        dc_card.pack(fill="x", pady=(0, 10))
        tk.Checkbutton(dc_card, text="啟用 Discord Bot（重啟生效）", variable=self.discord_enabled_var).pack(
            padx=8, pady=6, anchor="w"
        )
        tk.Label(dc_card, text="Discord Bot Token").pack(padx=8, pady=(4, 2), anchor="w")
        token_row = tk.Frame(dc_card)
        token_row.pack(fill="x", padx=8, pady=(0, 8))
        self.discord_token_entry = tk.Entry(token_row, textvariable=self.discord_token_var, show="*")
        self.discord_token_entry.pack(side="left", fill="x", expand=True)
        self.toggle_discord_token_btn = tk.Button(
            token_row, text="顯示", command=self.toggle_discord_token_visibility
        )
        self.toggle_discord_token_btn.pack(side="left", padx=(8, 0))

        tk.Label(dc_card, text="指令同步伺服器 ID（可選，多個以「,」分隔）").pack(padx=8, pady=(4, 2), anchor="w")
        tk.Label(
            dc_card,
            text="⚡ 填入後指令立即生效；多個伺服器請以英文逗號分隔，例：123456,789012\n   留空則全域同步（最多等 1 小時）",
            font=("Microsoft JhengHei", 9),
            justify="left",
        ).pack(padx=8, pady=(0, 2), anchor="w")
        guild_row = tk.Frame(dc_card)
        guild_row.pack(fill="x", padx=8, pady=(0, 8))
        tk.Entry(guild_row, textvariable=self.discord_sync_guild_var).pack(
            side="left", fill="x", expand=True
        )
        tk.Label(guild_row, text="（重啟生效）", font=("Microsoft JhengHei", 9)).pack(
            side="left", padx=(6, 0)
        )

        cost_card = tk.LabelFrame(content, text="成本模型設定（供用量頁估算）")
        cost_card.pack(fill="x")
        self._add_entry(cost_card, "每秒基準成本（USD）", self.cost_per_second_var)
        row = tk.Frame(cost_card)
        row.pack(fill="x", padx=8, pady=(0, 8))
        for lbl, var in (
            ("720p 乘數", self.mult_720_var),
            ("1080p 乘數", self.mult_1080_var),
            ("2K 乘數", self.mult_2k_var),
            ("4K 乘數", self.mult_4k_var),
        ):
            b = tk.Frame(row)
            b.pack(side="left", padx=6)
            tk.Label(b, text=lbl).pack(anchor="w")
            tk.Entry(b, textvariable=var, width=10).pack()

        action = tk.Frame(content)
        action.pack(fill="x", pady=12)
        tk.Button(action, text="一鍵套用 Google 官方預設", command=self.apply_google_defaults).pack(
            side="left"
        )
        tk.Button(action, text="重啟應用程式", command=self.restart_application).pack(side="right", padx=(8, 0))
        tk.Button(action, text="儲存設定", command=self.save_config_from_form).pack(side="right")

        self._load_config_into_form()
        cfg = load_config()
        first_backup = cfg.get("backup_apis", [{}])[0] if cfg.get("backup_apis") else {}
        self.backup_masked_key_label.config(
            text=f"目前備用 API Key: {mask_key(first_backup.get('api_key', '')) or '未設定'}"
        )
        self._apply_settings_theme()

    def _get_quality_multipliers(self) -> dict[str, float]:
        try:
            return {
                "720p": float(self.mult_720_var.get() or "1.0"),
                "1080p": float(self.mult_1080_var.get() or "1.4"),
                "2k": float(self.mult_2k_var.get() or "2.0"),
                "4k": float(self.mult_4k_var.get() or "3.2"),
            }
        except ValueError:
            return {"720p": 1.0, "1080p": 1.4, "2k": 2.0, "4k": 3.2}

    def apply_google_defaults(self):
        self.api_base_var.set(self._google_default_base())
        if not self.model_var.get().strip():
            self.model_var.set(self._google_default_model())
        else:
            self.model_var.set(self._google_default_model())

        # Backup defaults: keep model aligned, avoid force-overwriting key.
        if not self.backup_api_base_var.get().strip():
            self.backup_api_base_var.set(self._google_default_base())
        self.backup_model_var.set(self._google_default_model())
        self.set_status("已套用 Google 官方預設，可按儲存設定。")

    def toggle_discord_token_visibility(self):
        if not hasattr(self, "discord_token_entry") or not self.discord_token_entry.winfo_exists():
            return
        is_hidden = self.discord_token_entry.cget("show") == "*"
        self.discord_token_entry.configure(show="" if is_hidden else "*")
        if hasattr(self, "toggle_discord_token_btn") and self.toggle_discord_token_btn.winfo_exists():
            self.toggle_discord_token_btn.configure(text="隱藏" if is_hidden else "顯示")

    def _estimate_cost(self, duration_seconds: int, quality: str) -> float:
        try:
            unit = float(self.cost_per_second_var.get() or "0.04")
        except ValueError:
            unit = 0.04
        mult = self._get_quality_multipliers().get((quality or "").lower(), 1.0)
        return duration_seconds * unit * mult

    def open_usage_page(self):
        if self.usage_window and self.usage_window.winfo_exists():
            self.refresh_usage_dashboard()
            self.usage_window.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("API 用量與預估花費")
        win.geometry("940x720")
        win.minsize(620, 460)
        self._apply_window_icon(win)
        self._register_window_controls(win)
        self.usage_window = win

        shell = tk.Frame(win, padx=16, pady=14)
        shell.pack(fill="both", expand=True)
        tk.Label(shell, text="API 用量與預估花費儀表板", font=("Microsoft JhengHei", 15, "bold")).pack(anchor="w")
        tk.Label(
            shell,
            text="依據歷史命令統計總使用量，並用設定頁面的成本參數估算花費。",
        ).pack(anchor="w", pady=(2, 10))

        summary = tk.Frame(shell)
        summary.pack(fill="x", pady=(0, 10))
        self.stat_total_cmd = tk.Label(summary, text="總命令：0")
        self.stat_done_cmd = tk.Label(summary, text="成功生成：0")
        self.stat_total_sec = tk.Label(summary, text="總秒數：0")
        self.stat_total_cost = tk.Label(summary, text="累積預估費用：$0.00")
        for w in (self.stat_total_cmd, self.stat_done_cmd, self.stat_total_sec, self.stat_total_cost):
            w.pack(anchor="w")

        single_card = tk.LabelFrame(shell, text="單次生成預估")
        single_card.pack(fill="x", pady=(0, 10))
        row = tk.Frame(single_card)
        row.pack(fill="x", padx=8, pady=8)
        self.usage_duration_var = tk.StringVar(value=self.duration_var.get())
        self.usage_quality_var = tk.StringVar(value=self.quality_var.get())
        self._add_option(row, "預估秒數", self.usage_duration_var, ["4", "6", "8", "12", "16"])
        self._add_option(row, "預估畫質", self.usage_quality_var, ["720p", "1080p", "2k", "4k"])
        tk.Button(row, text="計算單次費用", command=self._refresh_single_estimate).pack(side="left", padx=10)
        self.single_estimate_label = tk.Label(single_card, text="單次預估：$0.00")
        self.single_estimate_label.pack(anchor="w", padx=8, pady=(0, 8))

        chart_card = tk.LabelFrame(shell, text="畫質使用分佈")
        chart_card.pack(fill="both", expand=True)
        self.usage_canvas = tk.Canvas(chart_card, height=240, highlightthickness=0)
        self.usage_canvas.pack(fill="both", expand=True, padx=8, pady=8)

        actions = tk.Frame(shell)
        actions.pack(fill="x", pady=(8, 0))
        tk.Button(actions, text="重新整理統計", command=self.refresh_usage_dashboard).pack(side="right")

        self.refresh_usage_dashboard()
        self._apply_usage_theme()

    def _refresh_single_estimate(self):
        try:
            secs = int(self.usage_duration_var.get())
        except ValueError:
            secs = 8
        est = self._estimate_cost(secs, self.usage_quality_var.get())
        self.single_estimate_label.config(text=f"單次預估：${est:.4f}")

    def refresh_usage_dashboard(self):
        if not self.usage_window or not self.usage_window.winfo_exists():
            return
        db = SessionLocal()
        try:
            rows = db.query(CommandRecord).order_by(CommandRecord.created_at.asc()).all()
        finally:
            db.close()

        total_commands = len(rows)
        done_rows = [r for r in rows if r.status == "done"]
        total_done = len(done_rows)
        total_seconds = sum(int(r.duration_seconds or 0) for r in done_rows)
        total_cost = sum(self._estimate_cost(int(r.duration_seconds or 0), r.quality or "1080p") for r in done_rows)

        self.stat_total_cmd.config(text=f"總命令：{total_commands}")
        self.stat_done_cmd.config(text=f"成功生成：{total_done}")
        self.stat_total_sec.config(text=f"總秒數：{total_seconds}")
        self.stat_total_cost.config(text=f"累積預估費用：${total_cost:.4f}")
        self._refresh_single_estimate()
        self._draw_quality_usage_chart(done_rows)

    def _draw_quality_usage_chart(self, rows: list[CommandRecord]):
        counts = {"720p": 0, "1080p": 0, "2k": 0, "4k": 0}
        for r in rows:
            key = (r.quality or "1080p").lower()
            counts[key] = counts.get(key, 0) + 1

        canvas = self.usage_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 640)
        height = max(canvas.winfo_height(), 220)
        pad_x = 40
        bar_w = 120
        gap = 40
        max_count = max(counts.values()) if counts else 1
        colors = {
            "720p": "#7ec8ff",
            "1080p": "#34c759",
            "2k": "#ff9f0a",
            "4k": "#ff375f",
        }
        base_y = height - 35
        keys = ["720p", "1080p", "2k", "4k"]
        for i, key in enumerate(keys):
            x1 = pad_x + i * (bar_w + gap)
            x2 = x1 + bar_w
            value = counts.get(key, 0)
            h = 0 if max_count == 0 else int((value / max_count) * (height - 90))
            y1 = base_y - h
            y2 = base_y
            canvas.create_rectangle(x1, y1, x2, y2, fill=colors[key], outline="")
            canvas.create_text((x1 + x2) / 2, y1 - 14, text=str(value))
            canvas.create_text((x1 + x2) / 2, base_y + 14, text=key.upper())

    def _apply_settings_theme(self):
        if not self.settings_window or not self.settings_window.winfo_exists() or not self.palette:
            return
        self._paint_widget_tree(self.settings_window, self.palette)
        self.settings_window.configure(bg=self.palette["bg"])

    def _apply_usage_theme(self):
        if not self.usage_window or not self.usage_window.winfo_exists() or not self.palette:
            return
        self._paint_widget_tree(self.usage_window, self.palette)
        self.usage_window.configure(bg=self.palette["bg"])
        if hasattr(self, "usage_canvas"):
            self.usage_canvas.configure(bg=self.palette["input"])

    def _apply_usage_guide_theme(self):
        if not self.usage_guide_window or not self.usage_guide_window.winfo_exists() or not self.palette:
            return
        self._paint_widget_tree(self.usage_guide_window, self.palette)
        self.usage_guide_window.configure(bg=self.palette["bg"])

    def _apply_gemini_tutorial_theme(self):
        if not self.gemini_tutorial_window or not self.gemini_tutorial_window.winfo_exists() or not self.palette:
            return
        self._paint_widget_tree(self.gemini_tutorial_window, self.palette)
        self.gemini_tutorial_window.configure(bg=self.palette["bg"])

    def restart_application(self):
        launcher = Path(__file__).resolve().parent.parent / "launcher.py"
        if not launcher.exists():
            messagebox.showerror("重啟失敗", "找不到 launcher.py，請手動重新啟動。")
            return
        self._save_ui_state()
        self.root.after(120, lambda: os.execl(sys.executable, sys.executable, str(launcher)))
        self.root.destroy()

    def on_app_close(self):
        self._save_ui_state()
        self.root.destroy()

    def open_usage_guide(self):
        if self.usage_guide_window and self.usage_guide_window.winfo_exists():
            self.usage_guide_window.lift()
            return

        guide = tk.Toplevel(self.root)
        guide.title("應用程式使用教學")
        guide.geometry("980x760")
        guide.minsize(620, 460)
        self._apply_window_icon(guide)
        self._register_window_controls(guide)
        self.usage_guide_window = guide

        shell = tk.Frame(guide, padx=14, pady=14)
        shell.pack(fill="both", expand=True)
        tk.Label(shell, text="Veo Local Studio 完整使用教學", font=("Microsoft JhengHei", 16, "bold")).pack(anchor="w")
        tk.Label(shell, text="本頁僅說明應用程式本體，不含 Discord Bot。").pack(anchor="w", pady=(2, 10))

        viewport = tk.Frame(shell)
        viewport.pack(fill="both", expand=True)
        canvas = tk.Canvas(viewport, highlightthickness=0)
        scrollbar = tk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas)
        content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._bind_canvas_wheel(canvas)

        self._add_tutorial_section(
            content,
            "Step 1 - 開啟設定頁面",
            "主畫面右上按「設定頁面」，先填入 API Base URL、API Key、模型名稱。\n"
            "若要容錯，請同時填寫備用 AI API 欄位，主 API 失敗會自動切換。",
        )
        self._add_tutorial_section(
            content,
            "Step 2 - 儲存設定",
            "在設定頁按「儲存設定」。若切換了 Bot 或重要參數，可按「重啟應用程式」。",
        )
        self._add_tutorial_code_block(content, "快速啟動命令", "scripts\\run_local.bat")
        self._add_tutorial_section(
            content,
            "Step 3 - 建立對話",
            "左側按「+ 新對話」，每個對話都會保存生成紀錄，方便回看和重跑。",
        )
        self._add_tutorial_section(
            content,
            "Step 4 - 輸入指令與素材",
            "在主頁輸入 Prompt，並可選擇或拖放素材。\n"
            "素材清單可排序，指令中可用 @圖1、@圖2 對應。",
        )
        self._add_tutorial_section(
            content,
            "Step 5 - 設定影片輸出",
            "選擇影片秒數、畫面比例、畫質後按「生成影片」。",
        )
        self._add_tutorial_section(
            content,
            "Step 6 - 查看結果與重跑",
            "右側歷史命令可載入舊參數再修改重跑。\n"
            "影片固定輸出在 outputs/videos，可按「打開輸出資料夾」查看。",
        )
        self._add_tutorial_section(
            content,
            "Step 7 - 查看用量與預估花費",
            "右上按「用量與花費」可看總命令、總秒數、畫質分布與預估成本。",
        )
        self._add_tutorial_code_block(
            content,
            "Prompt 範例",
            "請以 @圖1 的主體和 @圖2 的背景風格，生成 8 秒 16:9 的 cinematic 影片。",
        )
        self._add_tutorial_section(
            content,
            "常見問題",
            "Q: API 錯誤？先檢查設定頁 URL/Key/模型。\n"
            "Q: 無法拖放？請確認已安裝 tkinterdnd2，或先用「選擇素材」。\n"
            "Q: 指令對圖錯位？請先在素材清單用上移/下移調整順序。",
        )

        self._apply_usage_guide_theme()

    def open_gemini_tutorial(self):
        if self.gemini_tutorial_window and self.gemini_tutorial_window.winfo_exists():
            self.gemini_tutorial_window.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("Gemini API 保母級申請與專案使用教學")
        win.geometry("1020x780")
        win.minsize(640, 480)
        self._apply_window_icon(win)
        self._register_window_controls(win)
        self.gemini_tutorial_window = win

        shell = tk.Frame(win, padx=14, pady=14)
        shell.pack(fill="both", expand=True)
        tk.Label(
            shell,
            text="Gemini / Veo API 保母級教學（申請、帳單、專案接入）",
            font=("Microsoft JhengHei", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            shell,
            text="以下流程從官方文件入口開始，並說明在本專案如何正確填寫設定。",
        ).pack(anchor="w", pady=(2, 10))

        viewport = tk.Frame(shell)
        viewport.pack(fill="both", expand=True)
        canvas = tk.Canvas(viewport, highlightthickness=0)
        scrollbar = tk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas)
        content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._bind_canvas_wheel(canvas)

        self._add_tutorial_section(
            content,
            "Step 1 - 先進官方文件入口",
            "從這個頁面開始：Gemini API 文件（繁中），先確認你要用的是 Veo 3.1 影片能力。",
            button_text="開啟官方文件",
            button_command=lambda: webbrowser.open("https://ai.google.dev/gemini-api/docs?hl=zh-tw"),
        )
        self._add_tutorial_code_block(
            content,
            "官方文件連結",
            "https://ai.google.dev/gemini-api/docs?hl=zh-tw",
        )

        self._add_tutorial_section(
            content,
            "Step 2 - 申請 API Key（Google AI Studio）",
            "在文件頁點「取得 API 金鑰」，進入 Google AI Studio 建立 key。\n"
            "建立後先複製保存，避免離開後找不到。",
        )
        self._add_tutorial_code_block(content, "建議命名", "veo31-local-studio-primary")

        self._add_tutorial_section(
            content,
            "Step 3 - 帳單與配額設定",
            "進 Google Cloud/AI Studio 的帳單與配額頁，確認已綁定付款方式與專案配額。\n"
            "若是新帳戶，建議先設預算警示，避免超支。",
        )
        self._add_tutorial_code_block(
            content,
            "建議預算策略",
            "日預算：先從小額開始（例：USD 3~10）\n"
            "月預算：依需求設定（例：USD 30~100）\n"
            "超過 80% 觸發通知",
        )

        self._add_tutorial_section(
            content,
            "Step 4 - 常見帳單問題排查",
            "1) Key 可用但呼叫失敗：先查配額是否耗盡。\n"
            "2) 403/權限錯誤：確認 API 已啟用且帳單正常。\n"
            "3) 扣款異常：先查使用量圖表，再看是否有重試過多。\n"
            "4) 區域不可用：確認服務可用地區與模型可用性。",
        )

        self._add_tutorial_section(
            content,
            "Step 5 - 本專案怎麼填（設定頁）",
            "打開本程式「設定頁面」後填入：主 API Base URL、API Key、模型名稱。\n"
            "另可再填備用 API，主 API 失敗會自動切換。",
        )
        self._add_tutorial_code_block(
            content,
            "設定頁必填欄位",
            "主 API Base URL\n主 API Key\n模型名稱（例：veo-3.1）",
        )
        self._add_tutorial_code_block(
            content,
            "備援建議",
            "備用 API Base URL\n備用 API Key\n備用模型名稱",
        )

        self._add_tutorial_section(
            content,
            "Step 6 - 在本專案測試",
            "儲存設定後回主頁，輸入 prompt 並設定影片秒數/比例/畫質，點「生成影片」。\n"
            "若主 API 錯誤，系統會自動嘗試備援 API。",
        )
        self._add_tutorial_code_block(
            content,
            "測試 Prompt 範例",
            "請根據 @圖1 的主體風格，生成 8 秒、16:9、1080p 的電影感鏡頭。",
        )

        self._add_tutorial_section(
            content,
            "Step 7 - 成本控管",
            "到「用量與花費」頁查看命令數、總秒數、預估費用。\n"
            "必要時下修畫質乘數或長度，並保留預算警示。",
        )

        self._add_tutorial_section(
            content,
            "重要提醒（本專案 API 格式）",
            "設定頁填 Google 官方端點時，會走 Veo 的 long-running operation。\n"
            "若填自訂後端，則呼叫 POST {API_BASE}/generate，並接受 video_url 或 video_base64。",
        )

        self._apply_gemini_tutorial_theme()

    def open_discord_tutorial(self):
        if self.discord_tutorial_window and self.discord_tutorial_window.winfo_exists():
            self.discord_tutorial_window.lift()
            return

        tutorial = tk.Toplevel(self.root)
        tutorial.title("Discord Bot 保母級建立教學")
        tutorial.geometry("980x760")
        tutorial.minsize(620, 460)
        self._apply_window_icon(tutorial)
        self._register_window_controls(tutorial)
        self.discord_tutorial_window = tutorial

        shell = tk.Frame(tutorial, padx=14, pady=14)
        shell.pack(fill="both", expand=True)

        top = tk.Frame(shell)
        top.pack(fill="x", pady=(0, 10))
        tk.Label(top, text="Discord Bot 保母級建立教學", font=("Microsoft JhengHei", 16, "bold")).pack(anchor="w")
        tk.Label(
            top,
            text="從 0 到可用指令，照著做就能在本專案啟用 /veo3",
            font=("Microsoft JhengHei", 10),
        ).pack(anchor="w", pady=(3, 0))

        viewport = tk.Frame(shell)
        viewport.pack(fill="both", expand=True)
        canvas = tk.Canvas(viewport, highlightthickness=0)
        scrollbar = tk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas)
        content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._bind_canvas_wheel(canvas)

        self._add_tutorial_section(
            content,
            "Step 0 - 先啟動專案",
            "先跑本機啟動，確認主程式可開啟，接著再設定 Discord。",
        )
        self._add_tutorial_code_block(content, "啟動命令", "scripts\\run_local.bat")

        self._add_tutorial_section(
            content,
            "Step 1 - 建立 Discord Application",
            "到 Developer Portal 建立 Application，進入 Bot 分頁後按 Reset Token，保存 Token。",
            button_text="開啟 Developer Portal",
            button_command=lambda: webbrowser.open("https://discord.com/developers/applications"),
        )
        self._add_tutorial_code_block(content, "Developer Portal", "https://discord.com/developers/applications")

        self._add_tutorial_section(
            content,
            "Step 2 - OAuth2 權限設定",
            "在 OAuth2 > URL Generator 勾選 bot 與 applications.commands，並配置最少必要權限。",
        )
        self._add_tutorial_code_block(content, "Scopes", "bot\napplications.commands")
        self._add_tutorial_code_block(
            content,
            "建議 Bot Permissions",
            "Send Messages\nAttach Files\nRead Message History\nUse Slash Commands",
        )

        self._add_tutorial_section(
            content,
            "Step 3 - 邀請 Bot 到伺服器",
            "把 URL Generator 產生的邀請連結貼到瀏覽器，選伺服器授權，完成後回 Discord 確認 Bot 已進入。",
        )

        self._add_tutorial_section(
            content,
            "Step 4 - 在本專案啟用",
            "回到桌面程式勾選「啟用 Discord Bot」，貼上 Token，儲存後重啟專案。",
        )
        self._add_tutorial_code_block(content, "重啟命令", "scripts\\run_local.bat")
        self._add_tutorial_code_block(content, "成功訊息範例", "Discord bot 已上線：<你的 Bot 名稱>")

        self._add_tutorial_section(
            content,
            "Step 5 - 在 Discord 測試",
            "在有權限的頻道執行 /veo3，依選單設定片長、比例、畫質與生成類型，再於頻道輸入提示詞與素材。",
        )
        self._add_tutorial_code_block(
            content,
            "Slash 指令",
            "/veo3",
        )

        self._add_tutorial_section(
            content,
            "常見錯誤排除",
            "看不到 /veo3：檢查 applications.commands、Message Content Intent，以及是否填了伺服器 ID。\n"
            "沒反應：檢查 Token 與啟用開關。\n"
            "生成失敗：先測桌面端，再檢查 API Base / Key / model。\n"
            "圖片報錯：圖片數量不可超過 max_image_inputs。",
        )

        self._add_tutorial_section(
            content,
            "安全提醒",
            "Discord Bot Token 就是密碼，勿外流。若懷疑洩漏，請立即 Reset Token。\n"
            "建議不要把 data/app_config.json 上傳到公開 Repository。",
        )

        self._apply_tutorial_theme()

    def _copy_text(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status("已複製到剪貼簿。")

    def _add_tutorial_section(
        self,
        parent: tk.Widget,
        title: str,
        body: str,
        button_text: str | None = None,
        button_command=None,
    ):
        card = tk.Frame(parent, padx=14, pady=12, bd=1, relief="solid")
        card.pack(fill="x", pady=6)
        tk.Label(card, text=title, font=("Microsoft JhengHei", 12, "bold")).pack(anchor="w")
        tk.Label(card, text=body, justify="left", anchor="w").pack(anchor="w", pady=(6, 0))
        if button_text and button_command:
            tk.Button(card, text=button_text, command=button_command).pack(anchor="e", pady=(8, 0))

    def _add_tutorial_code_block(self, parent: tk.Widget, title: str, code: str):
        card = tk.Frame(parent, padx=12, pady=10, bd=1, relief="solid")
        card.pack(fill="x", pady=(0, 8))
        row = tk.Frame(card)
        row.pack(fill="x")
        tk.Label(row, text=title, font=("Microsoft JhengHei", 10, "bold")).pack(side="left")
        tk.Button(row, text="複製", command=lambda c=code: self._copy_text(c)).pack(side="right")
        code_view = tk.Text(card, height=max(2, code.count("\n") + 1), wrap="word")
        code_view.insert("1.0", code)
        code_view.configure(state="disabled")
        code_view.pack(fill="x", pady=(6, 0))

    def _apply_tutorial_theme(self):
        if not self.discord_tutorial_window or not self.discord_tutorial_window.winfo_exists() or not self.palette:
            return
        self._paint_widget_tree(self.discord_tutorial_window, self.palette)
        self.discord_tutorial_window.configure(bg=self.palette["bg"])


def main():
    if DND_AVAILABLE and TkinterDnD is not None:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    VeoDesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
