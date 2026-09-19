"""
Veo 3.1 API client — supports 7 generation types:
  text_to_video   文字轉影片
  image_to_video  圖片轉影片
  ref_subject     參考圖片 - 指定主體
  ref_style       參考圖片 - 指定風格
  video_extend    影片擴充/延伸
  inpaint_insert  影片局部重繪 - 插入
  inpaint_remove  影片局部重繪 - 移除
"""
import base64
import json
import time
from pathlib import Path
from typing import Any

import requests

from ..config import load_config
from ..paths import ROOT
from .storage import save_video

# ─── 公開常數 ───────────────────────────────────────────────────────────────

GEN_TYPE_LABELS: dict[str, str] = {
    "text_to_video":  "文字轉影片",
    "image_to_video": "圖片轉影片",
    "ref_subject":    "參考圖片 - 指定主體",
    "ref_style":      "參考圖片 - 指定風格",
    "video_extend":   "影片擴充/延伸",
    "inpaint_insert": "影片局部重繪 - 插入",
    "inpaint_remove": "影片局部重繪 - 移除",
}

GEN_TYPES = list(GEN_TYPE_LABELS.keys())

# 需要至少一個媒體素材的類型
REQUIRES_MEDIA = {"image_to_video", "ref_subject", "ref_style",
                  "video_extend", "inpaint_insert", "inpaint_remove"}
# 需要影片的類型
REQUIRES_VIDEO = {"video_extend", "inpaint_insert", "inpaint_remove"}


# ─── 費用估算 ────────────────────────────────────────────────────────────────

def estimate_cost(
    duration_seconds: int,
    quality: str,
    gen_type: str = "text_to_video",
) -> dict[str, float]:
    """
    回傳 {"tokens": int, "usd": float, "ntd": float}
    Token 定義：每秒 720p = 1000 tokens，依畫質乘數縮放。
    """
    cfg = load_config()
    cost_per_sec: float = float(cfg.get("cost_per_second_usd", 0.04))
    mults: dict = cfg.get("quality_multipliers", {})
    ntd_rate: float = float(cfg.get("ntd_rate", 32.0))

    q_key = quality.lower()
    mult = float(mults.get(q_key, 1.0))

    # 影片類型加收 20%
    type_mult = 1.2 if gen_type in REQUIRES_VIDEO else 1.0

    tokens = int(duration_seconds * 1000 * mult * type_mult)
    usd = round(duration_seconds * cost_per_sec * mult * type_mult, 4)
    ntd = round(usd * ntd_rate, 2)
    return {"tokens": tokens, "usd": usd, "ntd": ntd}


# ─── 例外 ────────────────────────────────────────────────────────────────────

class VeoClientError(Exception):
    pass


# ─── 主入口 ──────────────────────────────────────────────────────────────────

def generate_video(
    prompt: str,
    images: list[dict[str, Any]],
    duration_seconds: int,
    aspect_ratio: str,
    quality: str,
    gen_type: str = "text_to_video",
) -> dict[str, Any]:
    """
    生成影片，支援 7 種生成模式。
    images 清單裡每個 dict 須含 mime_type、data_base64（可選 name）。
    """
    cfg = load_config()
    providers: list[dict[str, str]] = []

    primary = {
        "name": "primary",
        "api_base": (cfg.get("veo_api_base") or "").strip(),
        "api_key":  (cfg.get("veo_api_key")  or "").strip(),
        "model":    (cfg.get("veo_model") or "veo-3.1-generate-preview").strip()
                    or "veo-3.1-generate-preview",
    }
    if primary["api_base"] and primary["api_key"]:
        providers.append(primary)

    backup_apis = cfg.get("backup_apis", [])
    if isinstance(backup_apis, list):
        for idx, raw in enumerate(backup_apis, start=1):
            if not isinstance(raw, dict):
                continue
            candidate = {
                "name": f"backup-{idx}",
                "api_base": (raw.get("api_base") or "").strip(),
                "api_key":  (raw.get("api_key")  or "").strip(),
                "model":    (raw.get("model") or primary["model"]).strip()
                            or primary["model"],
            }
            if candidate["api_base"] and candidate["api_key"]:
                providers.append(candidate)

    if not providers:
        raise VeoClientError(
            "尚未在設定中填入可用的 API Base URL 與 API Key（主 API 或備用 API）。"
        )

    errors: list[str] = []
    for p in providers:
        try:
            if _is_google_official_base(p["api_base"]):
                body = _call_google_veo_api(
                    p["api_base"], p["api_key"], p["model"],
                    prompt, images, duration_seconds, aspect_ratio, quality,
                    gen_type,
                )
            else:
                url = f"{p['api_base'].rstrip('/')}/generate"
                payload = {
                    "prompt": prompt,
                    "images": images,
                    "video_options": {
                        "duration_seconds": duration_seconds,
                        "aspect_ratio": aspect_ratio,
                        "quality": quality,
                    },
                    "model": p["model"],
                    "gen_type": gen_type,
                }
                headers = {
                    "Authorization": f"Bearer {p['api_key']}",
                    "Content-Type": "application/json",
                }
                resp = requests.post(
                    url, headers=headers, data=json.dumps(payload), timeout=180
                )
                if resp.status_code >= 400:
                    errors.append(f"{p['name']}: HTTP {resp.status_code} {resp.text[:180]}")
                    continue
                body = resp.json()
        except requests.RequestException as exc:
            errors.append(f"{p['name']}: 呼叫失敗 {exc}")
            continue

        try:
            assert isinstance(body, dict)
        except Exception:
            errors.append(f"{p['name']}: 回應不是 JSON")
            continue

        try:
            if body.get("local_saved_path"):
                video_path = Path(body["local_saved_path"])
            else:
                video_path = _extract_video(body)
        except VeoClientError as exc:
            errors.append(f"{p['name']}: {exc}")
            continue

        cost = estimate_cost(duration_seconds, quality, gen_type)
        return {
            "provider_job_id": body.get("id") or body.get("job_id"),
            "video_path":      str(video_path),
            "video_web_path":  "/" + video_path.relative_to(ROOT).as_posix(),
            "raw_response":    body,
            "used_provider":   p["name"],
            "gen_type":        gen_type,
            "cost":            cost,
        }

    raise VeoClientError("所有 API 端點都失敗：\n" + "\n".join(errors))


# ─── 輔助函式 ────────────────────────────────────────────────────────────────

def _ext_from_mime(mime: str | None) -> str:
    return {
        "video/mp4":       ".mp4",
        "video/webm":      ".webm",
        "video/quicktime": ".mov",
    }.get((mime or "").lower(), ".mp4")


def _extract_video(body: dict[str, Any]) -> Path:
    if body.get("video_base64"):
        raw = base64.b64decode(body["video_base64"])
        suffix = _ext_from_mime(body.get("mime_type"))
        return save_video(raw, suffix=suffix)
    if body.get("video_url"):
        try:
            r = requests.get(body["video_url"], timeout=180)
            r.raise_for_status()
            return save_video(r.content, suffix=_ext_from_mime(r.headers.get("Content-Type")))
        except requests.RequestException as exc:
            raise VeoClientError(f"下載影片失敗：{exc}") from exc
    raise VeoClientError("Veo API 回應缺少 video_base64 或 video_url。")


def _is_google_official_base(api_base: str) -> bool:
    return "generativelanguage.googleapis.com" in (api_base or "").lower()


def _inline_data(item: dict[str, Any]) -> dict:
    return {
        "mimeType": item.get("mime_type") or "image/png",
        "data":     item.get("data_base64", ""),
    }


def _is_video_mime(mime: str) -> bool:
    return (mime or "").lower().startswith("video/")


# ─── Google 官方 API 呼叫 ────────────────────────────────────────────────────

def _call_google_veo_api(
    api_base: str,
    api_key: str,
    model: str,
    prompt: str,
    images: list[dict[str, Any]],
    duration_seconds: int,
    aspect_ratio: str,
    quality: str,
    gen_type: str,
) -> dict[str, Any]:
    base = api_base.rstrip("/")
    endpoint = f"{base}/models/{model}:predictLongRunning"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    instances = _build_instances(prompt, images, gen_type, duration_seconds)
    effective_duration = instances.pop("_effective_duration", duration_seconds)

    payload = {
        "instances": [instances],
        "parameters": {
            "aspectRatio":     aspect_ratio,
            "resolution":      quality,
            "durationSeconds": effective_duration,
        },
    }

    start_resp = requests.post(
        endpoint, headers=headers, data=json.dumps(payload), timeout=180
    )

    if start_resp.status_code >= 400:
        body_preview = start_resp.text[:500]
        # 若模型拒絕 inlineData，降級到純文字
        if ("inlineData" in body_preview and "isn't supported" in body_preview):
            payload["instances"] = [{"prompt": prompt}]
            payload["parameters"]["durationSeconds"] = duration_seconds
            start_resp = requests.post(
                endpoint, headers=headers, data=json.dumps(payload), timeout=180
            )
            if start_resp.status_code >= 400:
                raise VeoClientError(
                    f"Google API 啟動作業失敗 ({start_resp.status_code}): "
                    f"{start_resp.text[:300]}"
                )
        else:
            raise VeoClientError(
                f"Google API 啟動作業失敗 ({start_resp.status_code}): {body_preview[:300]}"
            )

    start_body = start_resp.json()
    operation_name = start_body.get("name")
    if not operation_name:
        raise VeoClientError("Google API 未回傳 operation name。")

    status_url = f"{base}/{operation_name}"
    deadline = time.time() + 60 * 8
    while True:
        status_resp = requests.get(
            status_url, headers={"x-goog-api-key": api_key}, timeout=60
        )
        if status_resp.status_code >= 400:
            raise VeoClientError(
                f"Google API 查詢作業失敗 ({status_resp.status_code})"
            )
        status = status_resp.json()
        if status.get("done") is True:
            break
        if time.time() > deadline:
            raise VeoClientError("Google API 生成逾時，請稍後再試。")
        time.sleep(10)

    # ── 列印完整回應以便 debug ──────────────────────────────────────────────
    print("[veo_client] done response keys:", list(status.keys()))
    resp_block = status.get("response", {})
    print("[veo_client] response block:", json.dumps(resp_block, ensure_ascii=False)[:800])

    # ── 若 API 回傳錯誤（如內容違規）──────────────────────────────────────
    if status.get("error"):
        err = status["error"]
        raise VeoClientError(
            f"Google API 生成失敗：{err.get('message', str(err))}"
        )

    # ── 嘗試多種 response 結構取出影片 URI ────────────────────────────────
    video_uri: str | None = None

    # 結構 A（官方標準）: response.generateVideoResponse.generatedSamples[0].video.uri
    samples = (
        resp_block.get("generateVideoResponse", {})
        .get("generatedSamples", [])
    )
    if samples:
        video_uri = samples[0].get("video", {}).get("uri")

    # 結構 B: response.videos[0].uri
    if not video_uri:
        videos = resp_block.get("videos", [])
        if videos:
            video_uri = videos[0].get("uri") or videos[0].get("url")

    # 結構 C: response.videoUri / response.video_url
    if not video_uri:
        video_uri = (
            resp_block.get("videoUri")
            or resp_block.get("video_url")
            or resp_block.get("uri")
        )

    # 結構 D：直接在 status 頂層
    if not video_uri:
        video_uri = status.get("videoUri") or status.get("video_url")

    if not video_uri:
        # 印出完整 status 幫助排查
        print("[veo_client] 無法解析影片 URI，完整 status：",
              json.dumps(status, ensure_ascii=False)[:1200])
        raise VeoClientError(
            "Google API 完成但未回傳影片下載連結。\n"
            "（詳細回應已印出至終端機，請截圖回報）"
        )

    video_resp = requests.get(
        video_uri,
        headers={"x-goog-api-key": api_key},
        timeout=180,
        allow_redirects=True,
    )
    video_resp.raise_for_status()
    suffix = _ext_from_mime(video_resp.headers.get("Content-Type"))
    path = save_video(video_resp.content, suffix=suffix)
    return {"job_id": operation_name, "local_saved_path": str(path)}


def _build_instances(
    prompt: str,
    images: list[dict[str, Any]],
    gen_type: str,
    duration_seconds: int,
) -> dict[str, Any]:
    """
    依 gen_type 組出 instances dict；
    附加 _effective_duration key 供呼叫方讀取後移除。
    """
    inst: dict[str, Any] = {"prompt": prompt}
    effective_duration = duration_seconds

    # ── 文字轉影片 ──────────────────────────────────────────────────────────
    if gen_type == "text_to_video":
        pass  # 只有 prompt

    # ── 圖片轉影片（第一張作為起始幀）──────────────────────────────────────
    elif gen_type == "image_to_video":
        if images:
            item = images[0]
            if _is_video_mime(item.get("mime_type", "")):
                # 影片作為起始幀
                inst["video"] = {"inlineData": _inline_data(item)}
            else:
                inst["image"] = {"inlineData": _inline_data(item)}
            effective_duration = 8  # 有媒體輸入時固定 8 秒

    # ── 參考圖片 - 指定主體 ──────────────────────────────────────────────────
    elif gen_type == "ref_subject":
        refs = []
        for item in images[:3]:
            refs.append({
                "image":         {"inlineData": _inline_data(item)},
                "referenceType": "SUBJECT",
            })
        if refs:
            inst["referenceImages"] = refs
            effective_duration = 8

    # ── 參考圖片 - 指定風格 ──────────────────────────────────────────────────
    elif gen_type == "ref_style":
        refs = []
        for item in images[:3]:
            refs.append({
                "image":         {"inlineData": _inline_data(item)},
                "referenceType": "STYLE",
            })
        if refs:
            inst["referenceImages"] = refs
            effective_duration = 8

    # ── 影片擴充/延伸（最後一幀作為起始）───────────────────────────────────
    elif gen_type == "video_extend":
        video_items = [i for i in images if _is_video_mime(i.get("mime_type", ""))]
        if video_items:
            item = video_items[0]
            inst["video"] = {"inlineData": _inline_data(item)}
            effective_duration = min(duration_seconds, 8)

    # ── 影片局部重繪 - 插入 ──────────────────────────────────────────────────
    elif gen_type == "inpaint_insert":
        video_items = [i for i in images if _is_video_mime(i.get("mime_type", ""))]
        mask_items  = [i for i in images if not _is_video_mime(i.get("mime_type", ""))]
        if video_items:
            inst["video"] = {"inlineData": _inline_data(video_items[0])}
        if mask_items:
            inst["maskImage"] = {"inlineData": _inline_data(mask_items[0])}
            inst["editMode"] = "inpainting-insert"
        effective_duration = min(duration_seconds, 8)

    # ── 影片局部重繪 - 移除 ──────────────────────────────────────────────────
    elif gen_type == "inpaint_remove":
        video_items = [i for i in images if _is_video_mime(i.get("mime_type", ""))]
        mask_items  = [i for i in images if not _is_video_mime(i.get("mime_type", ""))]
        if video_items:
            inst["video"] = {"inlineData": _inline_data(video_items[0])}
        if mask_items:
            inst["maskImage"] = {"inlineData": _inline_data(mask_items[0])}
            inst["editMode"] = "inpainting-remove"
        effective_duration = min(duration_seconds, 8)

    inst["_effective_duration"] = effective_duration
    return inst
