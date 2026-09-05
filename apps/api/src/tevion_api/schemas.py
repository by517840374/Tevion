from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ProductMetadata(BaseModel):
    name: str = "Tevion"
    stage: str = "product-foundation"
    initial_goal: str = "clearly adult male portraits with fresh youthful energy and deliberate lighting"
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
    UNKNOWN = "unknown"
    RECOVERY_REQUIRED = "recovery_required"


class CreateTaskRequest(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None
    parent_version_id: str | None = None
    mode: str = Field(default="explore", pattern="^(explore|refine)$")
    output_count: int = Field(default=4, ge=2, le=4)
    aspect_ratio: str = Field(default="4:5", pattern=r"^\d+:\d+$")


class TaskSummary(BaseModel):
    task_id: str
    run_id: str
    user_id: str
    status: TaskStatus
    request: str
    mode: str
    output_count: int
    aspect_ratio: str
    parent_image_id: str | None = None
    parent_run_id: str | None = None


class ImageSummary(BaseModel):
    id: str
    url: str
    width: int | None = None
    height: int | None = None
    parent_image_id: str | None = None


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: str | None = None


class ProjectListResponse(BaseModel):
    items: list[ProjectSummary] = Field(default_factory=list)


class SessionSummary(BaseModel):
    id: str
    project_id: str
    mode: str
    status: str
    request: str
    created_at: datetime


class SessionListResponse(BaseModel):
    items: list[SessionSummary] = Field(default_factory=list)


class ImageVersionListResponse(BaseModel):
    items: list[ImageSummary] = Field(default_factory=list)


class TaskDetail(BaseModel):
    task_id: str
    status: TaskStatus
    mode: str
    request: str
    run_id: str
    parent_run_id: str | None = None
    strategy_version: str
    output_count: int | None = None
    aspect_ratio: str | None = None
    created_at: datetime
    images: list[ImageSummary] = Field(default_factory=list)
    phase: str | None = None
    provider_request_id: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_polled_at: datetime | None = None
    next_poll_at: datetime | None = None
    finalized_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    estimated_cost: float | None = None
    reconciliation_required: bool | None = None
    reconciliation_reason: str | None = None
    history: list["GenerationRunResponse"] = Field(default_factory=list)


class GenerationRunResponse(BaseModel):
    task_id: str
    run_id: str
    status: str
    phase: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    provider_request_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_polled_at: datetime | None = None
    next_poll_at: datetime | None = None
    finalized_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    estimated_cost: float | None = None
    images: list[ImageSummary] = Field(default_factory=list)
    reconciliation_required: bool | None = None
    reconciliation_reason: str | None = None


class GenerateRequest(BaseModel):
    output_count: int | None = Field(default=None, ge=1, le=4)
    aspect_ratio: str | None = Field(default=None, pattern=r"^\d+:\d+$")
    quality: str | None = Field(default=None, min_length=1, max_length=32)


class GenerateResponse(BaseModel):
    task_id: str
    status: TaskStatus
    run_id: str
    parent_run_id: str | None = None
    images: list[ImageSummary] = Field(default_factory=list)


class TaskRuntimeResponse(BaseModel):
    task_id: str
    state: TaskStatus
    session_status: str
    generation_status: str
    retry_count: int = 0
    max_retries: int = 2
    correlation_id: str
    event_count: int = 0


class DevTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthUserResponse(BaseModel):
    id: str
    auth_provider: str
    provider_subject: str
    email: str | None = None
    display_name: str | None = None


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
    accepted: bool | None = None
    selected: bool | None = None
    rejected: bool | None = None
    rejection_reason: str | None = Field(default=None, max_length=500)
    continue_direction: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_flags(self) -> "FeedbackRequest":
        if self.selected is None:
            self.selected = self.accepted
        if self.rejected is None and self.selected is not None:
            self.rejected = not self.selected
        if self.selected is None and self.rejected is None:
            raise ValueError("either accepted/selected or rejected must be provided")
        if self.selected and self.rejected:
            raise ValueError("selected and rejected cannot both be true")
        if self.rejected and not self.rejection_reason:
            raise ValueError("rejection_reason is required when rejected is true")
        return self


class FeedbackResponse(BaseModel):
    event_id: str
    task_id: str
    version_id: str
    event_type: str


PreferenceScope = Literal["project", "session", "user"]


class PreferenceView(BaseModel):
    key: str
    value: str
    source: str
    confidence: float
    scope: PreferenceScope
    scope_id: str | None = None
    evidence_count: int


class PreferenceListResponse(BaseModel):
    items: list[PreferenceView] = Field(default_factory=list)
