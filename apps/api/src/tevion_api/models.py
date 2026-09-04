"""SQLAlchemy ORM models for Tevion product data.

ID strategy: application-assigned text ids (e.g. `project_1`) so domain events
and API payloads keep the same identifier style already used by the runtime.
Timestamps are timezone-aware; JSON columns are PostgreSQL JSONB.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _ts() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("user"))
    auth_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("auth_provider", "provider_subject", name="uq_users_provider_subject"),)

    projects: Mapped[list["Project"]] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("project"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="projects")
    personas: Mapped[list["Persona"]] = relationship(back_populates="project")
    sessions: Mapped[list["Session"]] = relationship(back_populates="project")


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("persona"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    reference_policy: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    created_at: Mapped[datetime] = _ts()

    project: Mapped[Project] = relationship(back_populates="personas")
    sessions: Mapped[list["Session"]] = relationship(back_populates="persona")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("session"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    persona_id: Mapped[str | None] = mapped_column(ForeignKey("personas.id", ondelete="SET NULL"))
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="explore")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="created")
    raw_request: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="sessions")
    persona: Mapped[Persona | None] = relationship(back_populates="sessions")
    runs: Mapped[list["GenerationRun"]] = relationship(back_populates="session")
    feedback_events: Mapped[list["FeedbackEvent"]] = relationship(back_populates="session")


class GenerationRun(Base):
    __tablename__ = "generation_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("run"))
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("generation_runs.id", ondelete="SET NULL"))
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    provider_name: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="created")
    parameters_json: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(48))
    error_message: Mapped[str | None] = mapped_column(Text)

    session: Mapped[Session] = relationship(back_populates="runs")
    image_versions: Mapped[list["ImageVersion"]] = relationship(back_populates="run")


class ImageVersion(Base):
    __tablename__ = "image_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("image"))
    run_id: Mapped[str] = mapped_column(ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False)
    parent_image_id: Mapped[str | None] = mapped_column(ForeignKey("image_versions.id", ondelete="SET NULL"))
    asset_uri: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    prompt: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _ts()

    run: Mapped[GenerationRun] = relationship(back_populates="image_versions")
    feedback_events: Mapped[list["FeedbackEvent"]] = relationship(back_populates="image_version")


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("feedback"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    image_version_id: Mapped[str] = mapped_column(ForeignKey("image_versions.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _ts()

    user: Mapped[User] = relationship()
    session: Mapped[Session] = relationship(back_populates="feedback_events")
    image_version: Mapped[ImageVersion] = relationship(back_populates="feedback_events")


class PreferenceEvent(Base):
    __tablename__ = "preference_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: _new_id("pref_event"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _ts()

    user: Mapped[User] = relationship()
