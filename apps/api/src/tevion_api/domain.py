from typing import Any, Literal

from pydantic import BaseModel, Field

MemoryScope = Literal["session", "project", "user", "global"]


class Project(BaseModel):
    id: str
    user_id: str
    name: str


class Session(BaseModel):
    id: str
    project_id: str
    mode: Literal["explore", "refine"]


class GenerationRun(BaseModel):
    id: str
    session_id: str
    strategy_version: str


class ImageVersion(BaseModel):
    id: str
    run_id: str
    asset_uri: str


class FeedbackEvent(BaseModel):
    id: str
    user_id: str
    session_id: str
    image_version_id: str
    event_type: Literal["selected", "rejected", "rated", "edited", "downloaded"]
    payload: dict[str, Any] = Field(default_factory=dict)


class PreferenceEvent(BaseModel):
    id: str
    user_id: str
    scope: MemoryScope
    scope_id: str | None = None
    key: str
    value: str
    source: Literal["explicit_feedback", "tagged_feedback", "selection", "usage", "inference"]
    confidence: float = Field(ge=0, le=1)
