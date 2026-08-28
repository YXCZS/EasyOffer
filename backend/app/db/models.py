"""SQLAlchemy mappings for the existing EasyOffer MySQL schema.

These mappings intentionally mirror the current tables. They do not create or
alter tables at import time; Alembic owns schema changes.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, JSON, Numeric, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, CHAR, INTEGER, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    openid: Mapped[str] = mapped_column(VARCHAR(64), unique=True, nullable=False)
    nickname: Mapped[str] = mapped_column(VARCHAR(100), nullable=False, server_default="学习者")
    avatar_url: Mapped[str] = mapped_column(VARCHAR(500), nullable=False, server_default="")
    total_xp: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), server_onupdate=text("CURRENT_TIMESTAMP"))


class QuizSession(Base):
    __tablename__ = "quiz_sessions"
    __table_args__ = (Index("idx_quiz_sessions_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    quiz_id: Mapped[str] = mapped_column(VARCHAR(80), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    user_input: Mapped[str] = mapped_column(Text, nullable=False)
    questions_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class AnswerRecord(Base):
    __tablename__ = "answer_records"
    __table_args__ = (Index("idx_answer_records_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    quiz_id: Mapped[str] = mapped_column(VARCHAR(80), ForeignKey("quiz_sessions.quiz_id", ondelete="CASCADE", onupdate="CASCADE"), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    records_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    total_questions: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    correct_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    accuracy: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (Index("idx_reports_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    quiz_id: Mapped[str] = mapped_column(VARCHAR(80), ForeignKey("quiz_sessions.quiz_id", ondelete="CASCADE", onupdate="CASCADE"), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class QuizProgress(Base):
    __tablename__ = "quiz_progress"
    __table_args__ = (Index("idx_quiz_progress_user_status_updated", "user_id", "status", "updated_at"),)

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    quiz_id: Mapped[str] = mapped_column(VARCHAR(80), ForeignKey("quiz_sessions.quiz_id", ondelete="CASCADE", onupdate="CASCADE"), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(VARCHAR(32), nullable=False, server_default="general")
    difficulty: Mapped[str] = mapped_column(VARCHAR(16), nullable=False, server_default="medium")
    status: Mapped[str] = mapped_column(VARCHAR(32), nullable=False, server_default="in_progress")
    current_index: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    answer_records_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    answered_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    total_questions: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False)
    version: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="1")
    last_error: Mapped[str | None] = mapped_column(VARCHAR(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), server_onupdate=text("CURRENT_TIMESTAMP"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    abandoned_at: Mapped[datetime | None] = mapped_column(DateTime)


class QuizGenerationTask(Base):
    __tablename__ = "quiz_generation_tasks"
    __table_args__ = (
        Index("idx_quiz_generation_user_status", "user_id", "status", "updated_at"),
        Index("idx_quiz_generation_expiry", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(VARCHAR(80), unique=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"))
    guest_token_hash: Mapped[str | None] = mapped_column(CHAR(64))
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(Enum("queued", "generating", "completed", "failed", "expired", name="quiz_generation_status"), nullable=False, server_default="queued")
    generated_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    total_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="6")
    questions_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    answer_records_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    current_index: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    version: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="1")
    progress_version: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="1")
    title: Mapped[str] = mapped_column(VARCHAR(255), nullable=False, server_default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    quiz_id: Mapped[str | None] = mapped_column(VARCHAR(80), unique=True)
    quiz_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(VARCHAR(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), server_onupdate=text("CURRENT_TIMESTAMP"))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class GuestGenerationUsage(Base):
    __tablename__ = "guest_generation_usage"

    guest_token_hash: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    active_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), server_onupdate=text("CURRENT_TIMESTAMP"))


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (Index("idx_knowledge_user_status_updated", "user_id", "status", "updated_at"),)

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(VARCHAR(80), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    original_name: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(VARCHAR(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(VARCHAR(120), nullable=False)
    file_size: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    status: Mapped[str] = mapped_column(Enum("processing", "ready", "failed", name="knowledge_document_status"), nullable=False, server_default="processing")
    error_message: Mapped[str | None] = mapped_column(VARCHAR(500))
    chunk_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    embedding_model: Mapped[str | None] = mapped_column(VARCHAR(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), server_onupdate=text("CURRENT_TIMESTAMP"))


class QuizVisualAsset(Base):
    __tablename__ = "quiz_visual_assets"
    __table_args__ = (
        Index("idx_visual_asset_task", "task_id", "status"),
        Index("idx_visual_asset_quiz", "quiz_id", "question_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(VARCHAR(80), unique=True, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(VARCHAR(180), unique=True, nullable=False)
    task_id: Mapped[str | None] = mapped_column(VARCHAR(80))
    quiz_id: Mapped[str | None] = mapped_column(VARCHAR(80))
    question_id: Mapped[str] = mapped_column(VARCHAR(80), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), ForeignKey("users.id", ondelete="CASCADE"))
    guest_token_hash: Mapped[str | None] = mapped_column(CHAR(64))
    mode: Mapped[str] = mapped_column(Enum("image", name="visual_asset_mode"), nullable=False, server_default="image")
    visualization_type: Mapped[str] = mapped_column(VARCHAR(30), nullable=False, server_default="conceptual")
    provider: Mapped[str] = mapped_column(VARCHAR(50), nullable=False, server_default="dashscope")
    model_name: Mapped[str] = mapped_column(VARCHAR(100), nullable=False, server_default="z-image-turbo")
    status: Mapped[str] = mapped_column(Enum("pending", "generating", "uploading", "ready", "failed", name="visual_asset_status"), nullable=False, server_default="pending")
    prompt_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    image_prompt: Mapped[str] = mapped_column(VARCHAR(1200), nullable=False)
    alt_text: Mapped[str] = mapped_column(VARCHAR(200), nullable=False, server_default="")
    cos_key: Mapped[str | None] = mapped_column(VARCHAR(500))
    image_url: Mapped[str | None] = mapped_column(VARCHAR(2000))
    mime_type: Mapped[str | None] = mapped_column(VARCHAR(100))
    width: Mapped[int | None] = mapped_column(INTEGER)
    height: Mapped[int | None] = mapped_column(INTEGER)
    error_message: Mapped[str | None] = mapped_column(VARCHAR(500))
    retry_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"), server_onupdate=text("CURRENT_TIMESTAMP"))

