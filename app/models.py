from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="New Conversation")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    commands = relationship("CommandRecord", back_populates="conversation", cascade="all, delete-orphan")


class CommandRecord(Base):
    __tablename__ = "commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    image_paths: Mapped[str] = mapped_column(Text, default="[]")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=8)
    aspect_ratio: Mapped[str] = mapped_column(String(20), default="16:9")
    quality: Mapped[str] = mapped_column(String(50), default="1080p")
    provider_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    gen_type: Mapped[str] = mapped_column(String(50), default="text_to_video")
    source_command_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_discord: Mapped[bool] = mapped_column(Boolean, default=False)
    # 費用估算
    estimated_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(String(30), nullable=True)
    estimated_cost_ntd: Mapped[float | None] = mapped_column(String(30), nullable=True)
    elapsed_seconds: Mapped[float | None] = mapped_column(String(30), nullable=True)
    # Discord 來源資訊
    discord_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discord_guild: Mapped[str | None] = mapped_column(String(255), nullable=True)
    discord_channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("Conversation", back_populates="commands")
