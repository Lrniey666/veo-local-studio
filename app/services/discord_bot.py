"""
Discord Bot — /veo3 互動式多步驟影片生成指令
支援 7 種生成類型、動畫等待提示、費用估算、使用者資訊顯示與使用紀錄。

流程：
  /veo3
    └─ 第 1 步：SettingsView（4 個下拉選單）
    └─ 第 2 步：Bot 在頻道貼出提示，等待使用者回覆（提示詞 + 可附素材）
    └─ 第 3 步：ConfirmView（確認設定 → 生成）

注意：需在 Discord Developer Portal → Bot 啟用「Message Content Intent」。
"""
import asyncio
import base64
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import discord
from discord import app_commands, ui
from sqlalchemy.orm import Session

from ..config import load_config
from ..models import CommandRecord, Conversation
from .storage import save_uploaded_image
from .usage_logger import log_usage
from .veo_client import (
    GEN_TYPE_LABELS,
    GEN_TYPES,
    REQUIRES_MEDIA,
    REQUIRES_VIDEO,
    VeoClientError,
    estimate_cost,
    generate_video,
)

# ─── 生成類型常數 ──────────────────────────────────────────────────────────────

_GT_EMOJI = {
    "text_to_video":  "✍️",
    "image_to_video": "🖼️",
    "ref_subject":    "🎯",
    "ref_style":      "🎨",
    "video_extend":   "⏩",
    "inpaint_insert": "🖌️",
    "inpaint_remove": "🧹",
}

_GT_HINT = {
    "text_to_video":  "僅用文字描述即可生成，無需上傳任何素材",
    "image_to_video": "需上傳 1 張圖片，作為影片起始幀",
    "ref_subject":    "需上傳 1～3 張圖片，指定影片中的主體或角色",
    "ref_style":      "需上傳 1～3 張圖片，指定影片的整體視覺風格",
    "video_extend":   "需上傳 1 部影片，機器人會延伸影片內容",
    "inpaint_insert": "需上傳 1 部影片 + 1 張遮罩圖片，在指定區域插入內容",
    "inpaint_remove": "需上傳 1 部影片 + 1 張遮罩圖片，移除指定區域的內容",
}

# 頻道提示訊息：告訴使用者怎麼輸入
_GT_CHANNEL_GUIDE: dict[str, str] = {
    "text_to_video": (
        "✏️ 請在下方直接輸入你的 **提示詞**，然後按 Enter 送出。"
    ),
    "image_to_video": (
        "✏️📎 請在訊息框中輸入 **提示詞**，並同時附加 **1 張圖片**（作為起始幀）後送出。\n"
        "> 在 Discord 桌面版：訊息框輸入文字後，點擊 ＋ 號附加圖片，再一起送出。"
    ),
    "ref_subject": (
        "✏️📎 請在訊息框中輸入 **提示詞**，並同時附加 **1～3 張主體參考圖片** 後送出。"
    ),
    "ref_style": (
        "✏️📎 請在訊息框中輸入 **提示詞**，並同時附加 **1～3 張風格參考圖片** 後送出。"
    ),
    "video_extend": (
        "✏️🎬 請在訊息框中輸入 **提示詞（延伸方向）**，並同時附加 **1 部影片** 後送出。"
    ),
    "inpaint_insert": (
        "✏️🎬 請在訊息框中輸入 **提示詞（要插入的內容）**，\n"
        "並同時附加 **1 部影片** + **1 張遮罩圖片** 後送出。"
    ),
    "inpaint_remove": (
        "✏️🎬 請在訊息框中輸入 **提示詞（要移除的內容描述）**，\n"
        "並同時附加 **1 部影片** + **1 張遮罩圖片** 後送出。"
    ),
}

_EST_DURATION = 150

_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_PROGRESS_BLOCKS = [
    "▱▱▱▱▱▱▱▱▱▱", "▰▱▱▱▱▱▱▱▱▱", "▰▰▱▱▱▱▱▱▱▱",
    "▰▰▰▱▱▱▱▱▱▱", "▰▰▰▰▱▱▱▱▱▱", "▰▰▰▰▰▱▱▱▱▱",
    "▰▰▰▰▰▰▱▱▱▱", "▰▰▰▰▰▰▰▱▱▱", "▰▰▰▰▰▰▰▰▱▱",
    "▰▰▰▰▰▰▰▰▰▱", "▰▰▰▰▰▰▰▰▰▰",
]


# ─── 畫質 / 片長限制規則 ──────────────────────────────────────────────────────

# 各畫質最低需要的片長（秒）
_QUALITY_MIN_DURATION: dict[str, int] = {
    "720p":  4,
    "1080p": 8,
    "2K":    8,
}

# 各生成類型允許的最大片長（秒）；未列出表示使用預設最大值 8
_GENTYPE_MAX_DURATION: dict[str, int] = {
    "video_extend": 7,   # 測試確認上限為 7 秒
}

# 生成類型限制畫質（只允許特定畫質）
_GENTYPE_FORCE_QUALITY: dict[str, str] = {
    "video_extend": "720p",  # API 規定 video_extend 只支援 720p
}

# 生成類型要求固定片長 8 秒
_GENTYPE_REQUIRE_8S = {"ref_subject", "ref_style"}

# 官方支援的片長選項（秒）：4、6、8
_ALL_DURATIONS = [4, 6, 8]


def _allowed_durations(cfg: "VideoConfig") -> list[int]:
    """回傳目前 gen_type + quality 組合下合法的片長選項。"""
    min_dur = _QUALITY_MIN_DURATION.get(cfg.quality, 4)
    max_dur = _GENTYPE_MAX_DURATION.get(cfg.gen_type, 8)
    if cfg.gen_type in _GENTYPE_REQUIRE_8S:
        return [8]
    return [d for d in _ALL_DURATIONS if min_dur <= d <= max_dur]


def _fix_combo(cfg: "VideoConfig") -> str | None:
    """
    依 Gemini API Veo 3.1 規格自動修正不合法的 duration / quality / gen_type 組合。
    規格：
      - 片長：4、6、8 秒
      - 1080p / 2K → 只能 8 秒
      - video_extend → 只能 720p，最長 7 秒
      - ref_subject / ref_style → 只能 8 秒
    """
    warnings: list[str] = []
    label = GEN_TYPE_LABELS.get(cfg.gen_type, cfg.gen_type)

    # 1. 生成類型強制畫質
    forced_q = _GENTYPE_FORCE_QUALITY.get(cfg.gen_type)
    if forced_q and cfg.quality != forced_q:
        cfg.quality = forced_q
        warnings.append(f"{label} 僅支援 {forced_q}，畫質已自動調整")

    # 2. 生成類型要求 8 秒
    if cfg.gen_type in _GENTYPE_REQUIRE_8S and cfg.duration != 8:
        cfg.duration = 8
        warnings.append(f"{label} 僅支援 8 秒，片長已自動調整")

    # 3. 畫質要求最短片長
    min_dur = _QUALITY_MIN_DURATION.get(cfg.quality, 4)
    if cfg.duration < min_dur:
        cfg.duration = min_dur
        warnings.append(f"{cfg.quality} 最短需要 {min_dur} 秒，片長已自動調整")

    # 4. 生成類型最大片長
    max_dur = _GENTYPE_MAX_DURATION.get(cfg.gen_type, 8)
    if cfg.duration > max_dur:
        cfg.duration = max_dur
        warnings.append(f"{label} 最長支援 {max_dur} 秒，片長已自動調整")

    # 5. 片長必須是合法值（4 / 6 / 8），就近取值
    if cfg.duration not in _ALL_DURATIONS:
        closest = min(_ALL_DURATIONS, key=lambda d: abs(d - cfg.duration))
        cfg.duration = closest
        warnings.append(f"片長已調整為最近的合法值 {closest} 秒")

    return "⚠️ " + "；".join(warnings) + "。" if warnings else None


# ─── 資料結構 ──────────────────────────────────────────────────────────────────

@dataclass
class VideoConfig:
    duration:     int  = 8
    aspect_ratio: str  = "16:9"
    quality:      str  = "1080p"
    gen_type:     str  = "text_to_video"
    prompt:       str  = ""
    images:       list = field(default_factory=list)  # list[discord.Attachment]


# ─── Embed 工廠 ────────────────────────────────────────────────────────────────

def _fmt_elapsed(s: float) -> str:
    return f"{int(s // 60)} 分 {int(s % 60)} 秒" if s >= 60 else f"{s:.1f} 秒"


def _gt_label(gt: str) -> str:
    return f"{_GT_EMOJI.get(gt, '🎬')} {GEN_TYPE_LABELS.get(gt, gt)}"


def _settings_embed(cfg: VideoConfig, warn: str | None = None) -> discord.Embed:
    cost = estimate_cost(cfg.duration, cfg.quality, cfg.gen_type)
    needs_media = cfg.gen_type in REQUIRES_MEDIA
    e = discord.Embed(
        title="🎬 Veo 3.1 影片生成設定",
        description=(
            "請使用下方選單調整各項參數，完成後點擊「下一步 →」繼續。\n"
            "所有選項均已套用預設值，可直接跳過。"
        ),
        color=0xFEE75C if warn else 0x5865F2,
    )
    if warn:
        e.add_field(name="⚠️ 自動修正", value=warn, inline=False)
    e.add_field(name="⏱️ 片長",    value=f"`{cfg.duration} 秒`",   inline=True)
    e.add_field(name="📐 比例",    value=f"`{cfg.aspect_ratio}`",  inline=True)
    e.add_field(name="🎯 畫質",    value=f"`{cfg.quality}`",       inline=True)
    e.add_field(
        name="🎬 生成類型",
        value=f"{_gt_label(cfg.gen_type)}\n> ℹ️ {_GT_HINT.get(cfg.gen_type, '')}",
        inline=False,
    )
    e.add_field(
        name="💰 預估費用",
        value=f"`{cost['tokens']:,}` Token　≈ `${cost['usd']:.4f}` USD　≈ `NT${cost['ntd']:.2f}`",
        inline=False,
    )
    next_hint = "輸入提示詞 + 上傳素材" if needs_media else "輸入提示詞"
    e.set_footer(text=f"⚙️ 第 1 步，共 3 步　｜　下一步：{next_hint}")
    return e


def _waiting_embed(cfg: VideoConfig) -> discord.Embed:
    needs_media = cfg.gen_type in REQUIRES_MEDIA
    action = "提示詞 + 素材" if needs_media else "提示詞"
    e = discord.Embed(
        title=f"⌨️ 等待你輸入{action}…",
        description=(
            "**已在下方頻道發出提示訊息**，請依指示在訊息框輸入內容後送出。\n"
            "❌ 如需取消，請點擊下方「取消」按鈕。"
        ),
        color=0xFEE75C,
    )
    e.add_field(name="🎬 生成類型", value=_gt_label(cfg.gen_type), inline=True)
    e.add_field(name="⏱️ 片長",    value=f"`{cfg.duration} 秒`",  inline=True)
    e.add_field(name="🎯 畫質",    value=f"`{cfg.quality}`",      inline=True)
    e.set_footer(text="⚙️ 第 2 步，共 3 步　｜　等待中（無時間限制）")
    return e


def _confirm_embed(cfg: VideoConfig) -> discord.Embed:
    preview = cfg.prompt[:300] + "…" if len(cfg.prompt) > 300 else cfg.prompt
    cost = estimate_cost(cfg.duration, cfg.quality, cfg.gen_type)
    img_note = f"（{len(cfg.images)} 個素材）" if cfg.images else ""
    e = discord.Embed(
        title="📋 確認生成設定",
        description="請核對以下設定無誤，點擊「🎬 開始生成影片」即可開始。",
        color=0x57F287,
    )
    e.add_field(name="⏱️ 片長",    value=f"`{cfg.duration} 秒`",   inline=True)
    e.add_field(name="📐 比例",    value=f"`{cfg.aspect_ratio}`",  inline=True)
    e.add_field(name="🎯 畫質",    value=f"`{cfg.quality}`",       inline=True)
    e.add_field(name="🎬 類型",    value=_gt_label(cfg.gen_type) + "　" + img_note, inline=True)
    e.add_field(
        name="💰 預估費用",
        value=f"`{cost['tokens']:,}` Token　≈ `${cost['usd']:.4f}` USD　≈ `NT${cost['ntd']:.2f}`",
        inline=False,
    )
    e.add_field(name="✍️ 提示詞", value=f"```{preview}```", inline=False)
    e.set_footer(text="⚙️ 第 3 步，共 3 步")
    return e


def _loading_embed(cfg: VideoConfig, elapsed: float, frame: int) -> discord.Embed:
    spinner = _SPINNER[frame % len(_SPINNER)]
    prog_idx = min(int((elapsed / _EST_DURATION) * len(_PROGRESS_BLOCKS)), len(_PROGRESS_BLOCKS) - 1)
    bar = _PROGRESS_BLOCKS[prog_idx]
    remaining = max(0, _EST_DURATION - elapsed)
    p_short = cfg.prompt[:60] + "…" if len(cfg.prompt) > 60 else cfg.prompt

    phases = [(0, "🔄 初始化請求…"), (20, "📡 送出 API 請求…"),
              (40, "⚙️ 模型運算中…"), (80, "🎞️ 渲染影片中…"), (130, "📦 封裝輸出中…")]
    phase_text = next((t for s, t in reversed(phases) if elapsed >= s), phases[0][1])

    e = discord.Embed(
        title=f"{spinner} 正在生成影片…",
        description=(
            f"```\n{bar}\n```"
            f"**階段：** {phase_text}\n"
            f"**已耗時：** {_fmt_elapsed(elapsed)}　　**預估剩餘：** {_fmt_elapsed(remaining)}"
        ),
        color=0xFEE75C,
    )
    e.add_field(name="⏱️ 片長",    value=f"`{cfg.duration} 秒`",  inline=True)
    e.add_field(name="📐 比例",    value=f"`{cfg.aspect_ratio}`", inline=True)
    e.add_field(name="🎯 畫質",    value=f"`{cfg.quality}`",      inline=True)
    e.add_field(name="🎬 類型",    value=_gt_label(cfg.gen_type), inline=True)
    e.add_field(name="✍️ 提示詞", value=f"```{p_short}```",      inline=False)
    e.set_footer(text="💡 生成完成後影片將自動傳送至此頻道，請稍候…")
    return e


# ─── Select 元件 ───────────────────────────────────────────────────────────────

class _DurationSelect(ui.Select):
    def __init__(self, cfg: VideoConfig):
        self.cfg = cfg
        allowed = _allowed_durations(cfg)
        # 若目前 duration 不在合法範圍，先靜默修正
        if cfg.duration not in allowed:
            cfg.duration = allowed[-1]
        opts = [
            discord.SelectOption(
                label=f"{d} 秒", value=str(d), emoji="⏱️", default=(cfg.duration == d)
            )
            for d in allowed
        ]
        super().__init__(placeholder="⏱️ 選擇片長", options=opts, row=0)

    async def callback(self, inter: discord.Interaction):
        self.cfg.duration = int(self.values[0])
        warn = _fix_combo(self.cfg)
        for o in self.options:
            o.default = (o.value == str(self.cfg.duration))
        await inter.response.edit_message(embed=_settings_embed(self.cfg, warn), view=self.view)


class _AspectSelect(ui.Select):
    def __init__(self, cfg: VideoConfig):
        self.cfg = cfg
        opts = [
            discord.SelectOption(label="16:9 橫向", value="16:9", emoji="📺", default=cfg.aspect_ratio == "16:9"),
            discord.SelectOption(label="9:16 直向",  value="9:16", emoji="📱", default=cfg.aspect_ratio == "9:16"),
        ]
        super().__init__(placeholder="📐 選擇畫面比例", options=opts, row=1)

    async def callback(self, inter: discord.Interaction):
        self.cfg.aspect_ratio = self.values[0]
        for o in self.options:
            o.default = (o.value == self.values[0])
        await inter.response.edit_message(embed=_settings_embed(self.cfg), view=self.view)


class _QualitySelect(ui.Select):
    def __init__(self, cfg: VideoConfig):
        self.cfg = cfg
        opts = [
            discord.SelectOption(label="720p",  value="720p",  emoji="🔹", default=cfg.quality == "720p"),
            discord.SelectOption(label="1080p", value="1080p", emoji="🔷", default=cfg.quality == "1080p"),
            discord.SelectOption(label="2K",    value="2K",    emoji="💎", default=cfg.quality == "2K"),
        ]
        super().__init__(placeholder="🎯 選擇影片畫質", options=opts, row=2)

    async def callback(self, inter: discord.Interaction):
        self.cfg.quality = self.values[0]
        warn = _fix_combo(self.cfg)
        # 重建整個 SettingsView，讓 DurationSelect 的選項依新 quality 重新生成
        new_view = SettingsView(
            self.cfg, self.view.user_id, self.view.session_factory, self.view.client
        )
        await inter.response.edit_message(embed=_settings_embed(self.cfg, warn), view=new_view)


class _GenTypeSelect(ui.Select):
    def __init__(self, cfg: VideoConfig):
        self.cfg = cfg
        opts = [
            discord.SelectOption(
                label=f"{_GT_EMOJI[gt]} {GEN_TYPE_LABELS[gt]}",
                value=gt,
                default=(cfg.gen_type == gt),
                description=_GT_HINT.get(gt, "")[:100],
            )
            for gt in GEN_TYPES
        ]
        super().__init__(placeholder="🎬 選擇生成類型", options=opts, row=3)

    async def callback(self, inter: discord.Interaction):
        self.cfg.gen_type = self.values[0]
        warn = _fix_combo(self.cfg)
        # 重建整個 SettingsView，讓 DurationSelect 的選項依新 gen_type 重新生成
        new_view = SettingsView(
            self.cfg, self.view.user_id, self.view.session_factory, self.view.client
        )
        await inter.response.edit_message(embed=_settings_embed(self.cfg, warn), view=new_view)


# ─── 步驟一：設定畫面 ──────────────────────────────────────────────────────────

class SettingsView(ui.View):
    def __init__(self, cfg: VideoConfig, user_id: int, session_factory, client: discord.Client):
        super().__init__(timeout=600)
        self.cfg = cfg
        self.user_id = user_id
        self.session_factory = session_factory
        self.client = client

        self.add_item(_DurationSelect(cfg))
        self.add_item(_AspectSelect(cfg))
        self.add_item(_QualitySelect(cfg))
        self.add_item(_GenTypeSelect(cfg))

        btn = ui.Button(label="下一步 →", style=discord.ButtonStyle.primary, row=4)
        btn.callback = self._on_next
        self.add_item(btn)

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.user_id:
            await inter.response.send_message("❌ 這不是你的操作介面！", ephemeral=True)
            return False
        return True

    async def _on_next(self, inter: discord.Interaction):
        import traceback as _tb

        # 最後一次確認 duration/quality 組合合法
        _fix_combo(self.cfg)

        # 顯示等待輸入的 Embed（含取消按鈕）
        wait_view = _InputWaitView(self.cfg, self.user_id, self.session_factory, self.client)
        await inter.response.edit_message(embed=_waiting_embed(self.cfg), view=wait_view)

        # 在頻道貼出提示訊息
        guide_text = (
            f"{inter.user.mention}　{_GT_CHANNEL_GUIDE.get(self.cfg.gen_type, '請輸入提示詞並附上素材：')}"
        )
        guide_msg = await inter.channel.send(guide_text)

        # 記錄頻道 ID（避免 closure 中 inter 的 channel_id 被 gc 干擾）
        target_channel_id = inter.channel_id
        target_user_id    = self.user_id

        def check(m: discord.Message) -> bool:
            if m.author.id != target_user_id:
                return False
            if m.channel.id != target_channel_id:
                return False
            if m.content.startswith("/"):
                return False
            return bool(m.content.strip() or m.attachments)

        async def do_wait():
            try:
                # 無時間限制等待
                user_msg: discord.Message = await self.client.wait_for(
                    "message", check=check
                )

                if wait_view.is_cancelled:
                    return

                # 解析使用者輸入
                self.cfg.prompt = user_msg.content.strip() or "(無文字提示詞)"
                if user_msg.attachments:
                    self.cfg.images = list(user_msg.attachments)

                print(
                    f"[wait_for] 收到輸入 user={user_msg.author} "
                    f"prompt={self.cfg.prompt!r} attachments={len(self.cfg.images)}"
                )

                # 刪除頻道提示訊息（保留使用者的訊息）
                try:
                    await guide_msg.delete()
                except Exception:
                    pass

                # 提示使用者輸入已收到（短暫提示）
                await inter.channel.send(
                    f"✅ {inter.user.mention} 已收到你的輸入，請查看上方的確認卡片。",
                    delete_after=5,
                )

                # 顯示確認畫面
                confirm_view = ConfirmView(
                    self.cfg, self.user_id, self.session_factory, self.client
                )
                await inter.edit_original_response(
                    embed=_confirm_embed(self.cfg), view=confirm_view
                )

            except asyncio.CancelledError:
                pass
            except Exception as exc:
                print(f"[do_wait 錯誤] {type(exc).__name__}: {exc}")
                print(_tb.format_exc())
                if not wait_view.is_cancelled:
                    try:
                        await guide_msg.delete()
                    except Exception:
                        pass
                    err_e = discord.Embed(
                        title="⚠️ 發生錯誤",
                        description=f"等待輸入時發生例外：\n```{exc}```\n請重新使用 `/veo3` 指令。",
                        color=0xED4245,
                    )
                    try:
                        await inter.edit_original_response(embed=err_e, view=None)
                    except Exception:
                        pass

        wait_view.wait_task = asyncio.create_task(do_wait())


# ─── 步驟二：等待輸入時的 View（含取消按鈕）─────────────────────────────────────

class _InputWaitView(ui.View):
    def __init__(self, cfg: VideoConfig, user_id: int, session_factory, client: discord.Client):
        super().__init__(timeout=None)  # 無時間限制
        self.cfg = cfg
        self.user_id = user_id
        self.session_factory = session_factory
        self.client = client
        self.is_cancelled = False
        self.wait_task: asyncio.Task | None = None

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.user_id:
            await inter.response.send_message("❌ 這不是你的操作介面！", ephemeral=True)
            return False
        return True

    @ui.button(label="❌ 取消輸入", style=discord.ButtonStyle.danger, row=0)
    async def cancel(self, inter: discord.Interaction, _: ui.Button):
        self.is_cancelled = True
        if self.wait_task and not self.wait_task.done():
            self.wait_task.cancel()
        view = SettingsView(self.cfg, self.user_id, self.session_factory, self.client)
        await inter.response.edit_message(embed=_settings_embed(self.cfg), view=view)


# ─── 步驟三：確認畫面 ──────────────────────────────────────────────────────────

class ConfirmView(ui.View):
    def __init__(self, cfg: VideoConfig, user_id: int, session_factory, client: discord.Client):
        super().__init__(timeout=600)
        self.cfg = cfg
        self.user_id = user_id
        self.session_factory = session_factory
        self.client = client

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.user_id:
            await inter.response.send_message("❌ 這不是你的操作介面！", ephemeral=True)
            return False
        return True

    @ui.button(label="↩️ 返回修改", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, inter: discord.Interaction, _: ui.Button):
        view = SettingsView(self.cfg, self.user_id, self.session_factory, self.client)
        await inter.response.edit_message(embed=_settings_embed(self.cfg), view=view)

    @ui.button(label="🎬 開始生成影片", style=discord.ButtonStyle.success, row=0)
    async def start(self, inter: discord.Interaction, _: ui.Button):
        for item in self.children:
            item.disabled = True

        t0 = time.time()
        await inter.response.edit_message(embed=_loading_embed(self.cfg, 0, 0), view=self)

        anim_stop = asyncio.Event()
        anim_task = asyncio.get_running_loop().create_task(
            self._animate(inter, t0, anim_stop)
        )

        # 準備圖片 payload
        image_payloads: list[dict] = []
        stored_paths:   list[str]  = []
        for att in self.cfg.images:
            try:
                raw    = await att.read()
                suffix = Path(att.filename).suffix or ".png"
                sp     = save_uploaded_image(raw, suffix=suffix)
                stored_paths.append(str(sp))
                image_payloads.append({
                    "name":        att.filename,
                    "mime_type":   att.content_type or "image/png",
                    "data_base64": base64.b64encode(raw).decode("ascii"),
                })
            except Exception:
                pass

        guild_name = inter.guild.name       if inter.guild                    else "私訊"
        guild_id   = str(inter.guild.id)    if inter.guild                    else ""
        ch_name    = inter.channel.name     if hasattr(inter.channel, "name") else "私訊"
        ch_id      = str(inter.channel_id)  if inter.channel_id               else ""

        db: Session = self.session_factory() if self.session_factory else None
        cmd = None

        try:
            if db:
                conv = Conversation(title=f"Discord-{inter.user.display_name}")
                db.add(conv)
                db.flush()
                cmd = CommandRecord(
                    conversation_id=conv.id,
                    prompt=self.cfg.prompt,
                    image_paths=json.dumps(stored_paths, ensure_ascii=False),
                    duration_seconds=self.cfg.duration,
                    aspect_ratio=self.cfg.aspect_ratio,
                    quality=self.cfg.quality,
                    gen_type=self.cfg.gen_type,
                    status="running",
                    from_discord=True,
                    discord_user=inter.user.name,
                    discord_guild=guild_name,
                    discord_channel=ch_name,
                )
                db.add(cmd)
                db.commit()
                db.refresh(cmd)

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: generate_video(
                    prompt=self.cfg.prompt,
                    images=image_payloads,
                    duration_seconds=self.cfg.duration,
                    aspect_ratio=self.cfg.aspect_ratio,
                    quality=self.cfg.quality,
                    gen_type=self.cfg.gen_type,
                ),
            )

            elapsed     = time.time() - t0
            elapsed_str = _fmt_elapsed(elapsed)
            cost = result.get("cost", estimate_cost(
                self.cfg.duration, self.cfg.quality, self.cfg.gen_type
            ))

            if db and cmd:
                cmd.status             = "done"
                cmd.output_video_path  = result["video_web_path"]
                cmd.provider_job_id    = result.get("provider_job_id")
                cmd.raw_response       = json.dumps(result["raw_response"], ensure_ascii=False)
                cmd.estimated_tokens   = cost["tokens"]
                cmd.estimated_cost_usd = str(cost["usd"])
                cmd.estimated_cost_ntd = str(cost["ntd"])
                cmd.elapsed_seconds    = str(round(elapsed, 2))
                db.add(cmd)
                db.commit()

            anim_stop.set()
            await asyncio.sleep(0.2)
            anim_task.cancel()

            p_full = self.cfg.prompt[:300] + "…" if len(self.cfg.prompt) > 300 else self.cfg.prompt
            done_e = discord.Embed(title="✅ 影片生成完成！", color=0x57F287)
            done_e.add_field(name="⏱️ 片長",    value=f"`{self.cfg.duration} 秒`",   inline=True)
            done_e.add_field(name="📐 比例",    value=f"`{self.cfg.aspect_ratio}`",  inline=True)
            done_e.add_field(name="🎯 畫質",    value=f"`{self.cfg.quality}`",       inline=True)
            done_e.add_field(name="🎬 類型",    value=_gt_label(self.cfg.gen_type),  inline=True)
            done_e.add_field(name="🕐 生成用時", value=f"**{elapsed_str}**",          inline=True)
            done_e.add_field(
                name="💰 費用",
                value=(
                    f"預估 **{cost['tokens']:,}** Token，"
                    f"約 **NT${cost['ntd']:.2f}**（≈ **${cost['usd']:.4f}** USD）"
                ),
                inline=False,
            )
            done_e.add_field(name="✍️ 提示詞", value=f"```{p_full}```", inline=False)
            done_e.add_field(
                name="👤 來源資訊",
                value=(
                    f"**使用者：** {inter.user.display_name}（`{inter.user.name}`　ID:`{inter.user.id}`）\n"
                    f"**伺服器：** {guild_name}（ID:`{guild_id}`）\n"
                    f"**頻道：** #{ch_name}（ID:`{ch_id}`）"
                ),
                inline=False,
            )

            log_usage(
                source="discord",
                discord_user_name=inter.user.name,
                discord_user_id=str(inter.user.id),
                discord_guild_name=guild_name,
                discord_guild_id=guild_id,
                discord_channel_name=ch_name,
                discord_channel_id=ch_id,
                conversation_id=cmd.conversation_id if cmd else None,
                command_id=cmd.id if cmd else None,
                gen_type=self.cfg.gen_type,
                prompt=self.cfg.prompt,
                duration_seconds=self.cfg.duration,
                aspect_ratio=self.cfg.aspect_ratio,
                quality=self.cfg.quality,
                estimated_tokens=cost["tokens"],
                estimated_cost_usd=cost["usd"],
                estimated_cost_ntd=cost["ntd"],
                elapsed_seconds=elapsed,
                status="done",
                video_path=result["video_path"],
                provider=result.get("used_provider", ""),
            )

            done_view = _DoneView(self.cfg, self.user_id, self.session_factory, self.client)
            await inter.edit_original_response(embed=done_e, view=done_view)
            await inter.followup.send(
                content=(
                    f"🎉 {inter.user.mention} 你的影片已生成完成！\n"
                    f"> 預估 **{cost['tokens']:,}** Token，約 **NT${cost['ntd']:.2f}**"
                ),
                file=discord.File(result["video_path"]),
            )

        except (VeoClientError, Exception) as exc:
            anim_stop.set()
            try:
                anim_task.cancel()
            except Exception:
                pass

            elapsed     = time.time() - t0
            elapsed_str = _fmt_elapsed(elapsed)
            is_api_err  = isinstance(exc, VeoClientError)
            cost        = estimate_cost(self.cfg.duration, self.cfg.quality, self.cfg.gen_type)

            if db and cmd:
                cmd.status          = "error"
                cmd.error_message   = str(exc)
                cmd.elapsed_seconds = str(round(elapsed, 2))
                db.add(cmd)
                db.commit()

            log_usage(
                source="discord",
                discord_user_name=inter.user.name,
                discord_user_id=str(inter.user.id),
                discord_guild_name=guild_name,
                discord_guild_id=guild_id,
                discord_channel_name=ch_name,
                discord_channel_id=ch_id,
                conversation_id=cmd.conversation_id if cmd else None,
                command_id=cmd.id if cmd else None,
                gen_type=self.cfg.gen_type,
                prompt=self.cfg.prompt,
                duration_seconds=self.cfg.duration,
                aspect_ratio=self.cfg.aspect_ratio,
                quality=self.cfg.quality,
                estimated_tokens=cost["tokens"],
                estimated_cost_usd=cost["usd"],
                estimated_cost_ntd=cost["ntd"],
                elapsed_seconds=elapsed,
                status="error",
                error_message=str(exc),
            )

            title = "❌ 影片生成失敗" if is_api_err else "⚠️ 系統錯誤"
            err_e = discord.Embed(
                title=title,
                description=f"```{str(exc)[:500]}```",
                color=0xED4245,
            )
            err_e.add_field(name="🕐 耗時", value=elapsed_str, inline=True)
            err_e.add_field(
                name="👤 來源資訊",
                value=f"**使用者：** {inter.user.display_name}　**伺服器：** {guild_name}　**頻道：** #{ch_name}",
                inline=False,
            )
            retry_view = _RetryView(self.cfg, self.user_id, self.session_factory, self.client)
            await inter.edit_original_response(embed=err_e, view=retry_view)

        finally:
            if db:
                db.close()

    async def _animate(self, inter: discord.Interaction, t0: float, stop: asyncio.Event):
        frame = 0
        while not stop.is_set():
            await asyncio.sleep(6)
            if stop.is_set():
                break
            try:
                await inter.edit_original_response(
                    embed=_loading_embed(self.cfg, time.time() - t0, frame)
                )
            except Exception:
                break
            frame += 1


# ─── 完成後操作 ────────────────────────────────────────────────────────────────

class _DoneView(ui.View):
    def __init__(self, cfg: VideoConfig, user_id: int, session_factory, client: discord.Client):
        super().__init__(timeout=600)
        self.cfg = cfg
        self.user_id = user_id
        self.session_factory = session_factory
        self.client = client

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.user_id:
            await inter.response.send_message("❌ 這不是你的操作介面！", ephemeral=True)
            return False
        return True

    @ui.button(label="🔄 相同設定再生成一次", style=discord.ButtonStyle.primary, row=0)
    async def regen(self, inter: discord.Interaction, _: ui.Button):
        view = ConfirmView(self.cfg, self.user_id, self.session_factory, self.client)
        await inter.response.edit_message(embed=_confirm_embed(self.cfg), view=view)

    @ui.button(label="🆕 全新設定", style=discord.ButtonStyle.secondary, row=0)
    async def fresh(self, inter: discord.Interaction, _: ui.Button):
        new_cfg = VideoConfig()
        view = SettingsView(new_cfg, self.user_id, self.session_factory, self.client)
        await inter.response.edit_message(embed=_settings_embed(new_cfg), view=view)


# ─── 失敗重試 ──────────────────────────────────────────────────────────────────

class _RetryView(ui.View):
    def __init__(self, cfg: VideoConfig, user_id: int, session_factory, client: discord.Client):
        super().__init__(timeout=600)
        self.cfg = cfg
        self.user_id = user_id
        self.session_factory = session_factory
        self.client = client

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.user_id:
            await inter.response.send_message("❌ 這不是你的操作介面！", ephemeral=True)
            return False
        return True

    @ui.button(label="↩️ 返回修改設定", style=discord.ButtonStyle.secondary, row=0)
    async def back(self, inter: discord.Interaction, _: ui.Button):
        view = SettingsView(self.cfg, self.user_id, self.session_factory, self.client)
        await inter.response.edit_message(embed=_settings_embed(self.cfg), view=view)

    @ui.button(label="🔄 直接重試", style=discord.ButtonStyle.danger, row=0)
    async def retry(self, inter: discord.Interaction, _: ui.Button):
        view = ConfirmView(self.cfg, self.user_id, self.session_factory, self.client)
        await inter.response.edit_message(embed=_confirm_embed(self.cfg), view=view)


# ─── Bot 主體 ──────────────────────────────────────────────────────────────────

class DiscordVeoBot:
    def __init__(self, token: str, session_factory):
        self.token = token
        self.session_factory = session_factory

        intents = discord.Intents.default()
        intents.message_content = True   # 需在 Developer Portal 啟用 Message Content Intent

        self.client = discord.Client(intents=intents)
        self.tree = app_commands.CommandTree(self.client)
        self._register_commands()

    def _register_commands(self):
        import traceback as _tb
        client          = self.client
        session_factory = self.session_factory

        # ── 全域 app_command 錯誤捕捉（讓所有未處理例外顯示在終端並回應使用者）──
        @self.tree.error
        async def on_app_command_error(inter: discord.Interaction, error: app_commands.AppCommandError):
            cause = getattr(error, "__cause__", error)
            print(f"[Discord Bot 指令錯誤] {type(cause).__name__}: {cause}")
            print(_tb.format_exc())
            try:
                msg = f"❌ 指令執行失敗：`{cause}`\n請截圖此訊息並回報管理員。"
                if inter.response.is_done():
                    await inter.followup.send(msg, ephemeral=True)
                else:
                    await inter.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

        @self.tree.command(name="veo3", description="🎬 使用 Veo 3.1 互動式生成影片（支援 7 種模式）")
        async def veo3(inter: discord.Interaction):
            try:
                cfg  = VideoConfig()
                view = SettingsView(cfg, inter.user.id, session_factory, client)
                await inter.response.send_message(embed=_settings_embed(cfg), view=view)
            except Exception as exc:
                print(f"[veo3 指令錯誤] {type(exc).__name__}: {exc}")
                print(_tb.format_exc())
                try:
                    if not inter.response.is_done():
                        await inter.response.send_message(
                            f"❌ 指令初始化失敗：`{exc}`", ephemeral=True
                        )
                except Exception:
                    pass

        @self.client.event
        async def on_error(event: str, *args, **kwargs):
            print(f"[Discord Bot on_error] event={event}")
            _tb.print_exc()

        @self.client.event
        async def on_ready():
            cfg    = load_config()
            raw    = (cfg.get("discord_sync_guild_ids") or cfg.get("discord_sync_guild_id") or "").strip()
            guild_ids = [
                gid.strip() for gid in raw.replace("，", ",").split(",")
                if gid.strip().isdigit()
            ]

            print(f"✅ Discord Bot 已上線：{self.client.user}")

            try:
                if guild_ids:
                    for gid in guild_ids:
                        self.tree.copy_global_to(guild=discord.Object(id=int(gid)))
                    # 清空全域指令，避免重複
                    self.tree.clear_commands(guild=None)
                    await self.tree.sync()
                    print("   🧹 已清除全域指令（避免重複）")
                    for gid in guild_ids:
                        synced = await self.tree.sync(guild=discord.Object(id=int(gid)))
                        print(f"   ⚡ 已同步 {len(synced)} 個指令到伺服器 {gid}（立即生效）")
                else:
                    synced = await self.tree.sync()
                    print(f"   🌐 已全域同步 {len(synced)} 個指令（最多 1 小時後生效）")
            except Exception as exc:
                print(f"[on_ready sync 錯誤] {type(exc).__name__}: {exc}")
                _tb.print_exc()

    async def start(self):
        await self.client.start(self.token)


def run_bot_in_thread(token: str, session_factory):
    if not token:
        return None

    loop = asyncio.new_event_loop()

    def runner():
        asyncio.set_event_loop(loop)
        bot = DiscordVeoBot(token, session_factory)
        loop.run_until_complete(bot.start())

    t = threading.Thread(target=runner, daemon=True, name="discord-bot-thread")
    t.start()
    return t
