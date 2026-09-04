from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ProductMetadata(BaseModel):
    name: str = "Tevion"
    stage: str = "product-foundation"
    initial_goal: str = (
        "clearly adult male portraits with fresh youthful energy and deliberate lighting"
    )
    provider_status: str = "not_configured"


class TaskStatus(StrEnum):
    CREATED = "created"
    UNDERSTANDING = "understanding"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PLANNING = "planning"
    EXPLORING = "exploring"
    REFINING = "refining"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    AWAITING_SELECTION = "awaiting_selection"
    RETRYING = "retrying"
    NEEDS_USER_REVIEW = "needs_user_review"
    COMPLETED = "completed"


class CreateTaskRequest(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None
    mode: str = Field(default="explore", pattern="^(explore|refine)$")
    output_count: int = Field(default=4, ge=2, le=4)
    aspect_ratio: str = Field(default="4:5", pattern="^\\d+:\\d+$")


class TaskSummary(BaseModel):
    task_id: str
    user_id: str
    status: TaskStatus
    request: str
    mode: str
    output_count: int
    aspect_ratio: str


class ImageSummary(BaseModel):
    id: str
    url: str
    width: int | None = None
    height: int | None = None


class TaskDetail(BaseModel):
    task_id: str
    status: TaskStatus
    mode: str
    request: str
    run_id: str
    strategy_version: str
    output_count: int | None = None
    aspect_ratio: str | None = None
    created_at: datetime
    images: list[ImageSummary] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    task_id: str
    status: TaskStatus
    run_id: str
    images: list[ImageSummary] = Field(default_factory=list)


class DevTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "tevion-api"
    version: str = "0.1.0"


class Event(BaseModel):
    type: str
    task_id: str
    payload: dict = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    version_id: str
    accepted: bool
    rating: int | None = Field(default=None, ge=1, le=5)
    reason: str | None = None
    edit_request: str | None = None
