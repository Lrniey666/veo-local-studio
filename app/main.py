import base64
import json
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .config import load_config, mask_key, save_config
from .db import Base, SessionLocal, engine, get_db
from .models import CommandRecord, Conversation
from .schemas import AppConfigIn, AppConfigOut, CommandOut, ConversationCreate, ConversationOut
from .services.discord_bot import run_bot_in_thread
from .services.storage import save_uploaded_image
from .services.usage_logger import log_usage, read_recent, summary_stats
from .services.veo_client import VeoClientError, estimate_cost, generate_video

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
OUTPUTS_DIR = BASE_DIR / "outputs"

app = FastAPI(title="Veo 3.1 Local Studio", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")

_discord_thread = None


@app.on_event("startup")
def startup_event():
    global _discord_thread
    cfg = load_config()
    if cfg.get("discord_enabled") and cfg.get("discord_bot_token"):
        _discord_thread = run_bot_in_thread(cfg["discord_bot_token"], SessionLocal)


@app.get("/")
def read_index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/help")
def read_help():
    return FileResponse(STATIC_DIR / "help.html")


@app.get("/api/config", response_model=AppConfigOut)
def get_config():
    cfg = load_config()
    return AppConfigOut(
        veo_api_base=cfg.get("veo_api_base", ""),
        veo_api_key_masked=mask_key(cfg.get("veo_api_key", "")),
        veo_model=cfg.get("veo_model", "veo-3.1"),
        max_image_inputs=int(cfg.get("max_image_inputs", 8)),
        discord_enabled=bool(cfg.get("discord_enabled", False)),
    )


@app.put("/api/config")
def update_config(payload: AppConfigIn):
    current = load_config()
    incoming = payload.model_dump()
    if not incoming.get("veo_api_key"):
        incoming["veo_api_key"] = current.get("veo_api_key", "")
    if not incoming.get("discord_bot_token"):
        incoming["discord_bot_token"] = current.get("discord_bot_token", "")
    cfg = save_config(incoming)
    return {
        "ok": True,
        "veo_api_base": cfg["veo_api_base"],
        "veo_api_key_masked": mask_key(cfg["veo_api_key"]),
        "veo_model": cfg["veo_model"],
        "max_image_inputs": cfg["max_image_inputs"],
        "discord_enabled": cfg["discord_enabled"],
    }


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    items = db.query(Conversation).order_by(Conversation.updated_at.desc()).all()
    return items


@app.post("/api/conversations", response_model=ConversationOut)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)):
    row = Conversation(title=payload.title.strip() or "New Conversation")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@app.get("/api/conversations/{conversation_id}/commands", response_model=list[CommandOut])
def list_commands(conversation_id: int, db: Session = Depends(get_db)):
    rows = (
        db.query(CommandRecord)
        .filter(CommandRecord.conversation_id == conversation_id)
        .order_by(CommandRecord.created_at.asc())
        .all()
    )
    out: list[CommandOut] = []
    for r in rows:
        out.append(
            CommandOut(
                id=r.id,
                conversation_id=r.conversation_id,
                prompt=r.prompt,
                image_paths=json.loads(r.image_paths or "[]"),
                duration_seconds=r.duration_seconds,
                aspect_ratio=r.aspect_ratio,
                quality=r.quality,
                provider_job_id=r.provider_job_id,
                output_video_path=r.output_video_path,
                status=r.status,
                source_command_id=r.source_command_id,
                error_message=r.error_message,
                from_discord=r.from_discord,
                created_at=r.created_at,
                raw_response=json.loads(r.raw_response) if r.raw_response else None,
            )
        )
    return out


@app.post("/api/generate")
async def generate(
    conversation_id: int = Form(...),
    prompt: str = Form(...),
    duration_seconds: int = Form(8),
    aspect_ratio: str = Form("16:9"),
    quality: str = Form("1080p"),
    gen_type: str = Form("text_to_video"),
    source_command_id: int | None = Form(None),
    images: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
):
    import time as _time

    cfg = load_config()
    max_images = int(cfg.get("max_image_inputs", 8))
    if len(images) > max_images:
        raise HTTPException(status_code=400, detail=f"圖片數量不可超過 {max_images} 張")

    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="對話不存在")

    image_payloads = []
    image_paths = []
    for image in images:
        content = await image.read()
        suffix = Path(image.filename or "").suffix or ".png"
        stored = save_uploaded_image(content, suffix=suffix)
        image_paths.append(str(stored))
        image_payloads.append(
            {
                "name": image.filename,
                "mime_type": image.content_type or "image/png",
                "data_base64": base64.b64encode(content).decode("ascii"),
            }
        )

    row = CommandRecord(
        conversation_id=conversation_id,
        prompt=prompt,
        image_paths=json.dumps(image_paths, ensure_ascii=False),
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        quality=quality,
        gen_type=gen_type,
        source_command_id=source_command_id,
        status="running",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    t0 = _time.time()
    try:
        result = generate_video(
            prompt=prompt,
            images=image_payloads,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            quality=quality,
            gen_type=gen_type,
        )
        elapsed = _time.time() - t0
        cost = result.get("cost", estimate_cost(duration_seconds, quality, gen_type))
        row.status            = "done"
        row.output_video_path = result["video_web_path"]
        row.provider_job_id   = result.get("provider_job_id")
        row.raw_response      = json.dumps(result["raw_response"], ensure_ascii=False)
        row.estimated_tokens  = cost["tokens"]
        row.estimated_cost_usd = str(cost["usd"])
        row.estimated_cost_ntd = str(cost["ntd"])
        row.elapsed_seconds   = str(round(elapsed, 2))
        log_usage(
            source="api",
            conversation_id=row.conversation_id,
            command_id=row.id,
            gen_type=gen_type,
            prompt=prompt,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
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
        row.status = "error"
        row.error_message = str(exc)
        row.elapsed_seconds = str(round(elapsed, 2))
        log_usage(
            source="api",
            conversation_id=row.conversation_id,
            command_id=row.id,
            gen_type=gen_type,
            prompt=prompt,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            quality=quality,
            elapsed_seconds=elapsed,
            status="error",
            error_message=str(exc),
        )
    except Exception as exc:
        elapsed = _time.time() - t0
        row.status = "error"
        row.error_message = f"系統錯誤：{exc}"
        row.elapsed_seconds = str(round(elapsed, 2))

    db.add(row)
    db.add(conv)
    db.commit()
    db.refresh(row)

    return {
        "id": row.id,
        "status": row.status,
        "output_video_path": row.output_video_path,
        "error_message": row.error_message,
        "estimated_tokens": row.estimated_tokens,
        "estimated_cost_usd": row.estimated_cost_usd,
        "estimated_cost_ntd": row.estimated_cost_ntd,
        "elapsed_seconds": row.elapsed_seconds,
    }


@app.get("/api/usage/recent")
def get_usage_recent(n: int = 100):
    return read_recent(n)


@app.get("/api/usage/stats")
def get_usage_stats():
    return summary_stats()
