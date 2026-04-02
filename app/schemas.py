from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ConversationCreate(BaseModel):
    title: str


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class CommandOut(BaseModel):
    id: int
    conversation_id: int
    prompt: str
    image_paths: list[str]
    duration_seconds: int
    aspect_ratio: str
    quality: str
    gen_type: str = "text_to_video"
    provider_job_id: str | None = None
    output_video_path: str | None = None
    status: str
    source_command_id: int | None = None
    error_message: str | None = None
    from_discord: bool
    estimated_tokens: int | None = None
    estimated_cost_usd: str | None = None
    estimated_cost_ntd: str | None = None
    elapsed_seconds: str | None = None
    discord_user: str | None = None
    discord_guild: str | None = None
    discord_channel: str | None = None
    created_at: datetime
    raw_response: dict[str, Any] | None = None


class AppConfigIn(BaseModel):
    veo_api_base: str = ""
    veo_api_key: str = ""
    veo_model: str = "veo-3.1"
    max_image_inputs: int = 8
    discord_bot_token: str = ""
    discord_enabled: bool = False


class AppConfigOut(BaseModel):
    veo_api_base: str
    veo_api_key_masked: str
    veo_model: str
    max_image_inputs: int
    discord_enabled: bool
