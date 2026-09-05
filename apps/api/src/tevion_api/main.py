import os

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from . import services
from .auth import create_dev_token, get_auth_settings, get_current_user
from .cors import configure_cors
from .db import get_db
from .models import ImageVersion, User
from .provider import DEFAULT_MAIZI_BASE_URL, MaizitechImageProvider
from .schemas import (
    AuthUserResponse,
    CreateTaskRequest,
    DevTokenResponse,
    FeedbackRequest,
    FeedbackResponse,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    ImageSummary,
    ImageVersionListResponse,
    PreferenceListResponse,
    PreferenceView,
    ProductMetadata,
    ProjectListResponse,
    ProjectSummary,
    SessionListResponse,
    SessionSummary,
    TaskDetail,
    TaskRuntimeResponse,
    TaskStatus,
    TaskSummary,
)

app = FastAPI(title="Tevion Product API", version="0.1.0")

configure_cors(app)


def get_image_provider() -> MaizitechImageProvider:
    """Build the real provider from environment; tests override this dependency."""
    api_key = os.environ.get("MAIZI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="image provider is not configured")
    return MaizitechImageProvider(
        api_key=api_key,
        base_url=os.environ.get("MAIZI_BASE_URL", DEFAULT_MAIZI_BASE_URL),
        model_name=os.environ.get("MAIZI_MODEL", "gpt-image-2"),
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/v1/product", response_model=ProductMetadata)
def product_metadata() -> ProductMetadata:
    return ProductMetadata()


@app.post("/api/v1/auth/dev-token", response_model=DevTokenResponse)
def dev_token() -> DevTokenResponse:
    """Local-only endpoint issuing a demo token (disabled in production mode)."""
    settings = get_auth_settings()
    if settings.jwks_url or not settings.dev_secret:
        raise HTTPException(status_code=503, detail="dev token endpoint is disabled")
    return DevTokenResponse(access_token=create_dev_token("demo_user"))


@app.get("/api/v1/auth/me", response_model=AuthUserResponse)
def auth_me(current_user: User = Depends(get_current_user)) -> AuthUserResponse:
    return AuthUserResponse(
        id=current_user.id,
        auth_provider=current_user.auth_provider,
        provider_subject=current_user.provider_subject,
        email=current_user.email,
        display_name=current_user.display_name,
    )


@app.get("/api/v1/projects", response_model=ProjectListResponse)
def list_projects(
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> ProjectListResponse:
    return ProjectListResponse(
        items=[
            ProjectSummary(id=project.id, name=project.name, description=project.description)
            for project in services.list_projects_for_user(db, current_user.id)
        ]
    )


@app.get("/api/v1/projects/{project_id}/sessions", response_model=SessionListResponse)
def list_project_sessions(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> SessionListResponse:
    sessions = services.list_sessions_for_project(db, current_user.id, project_id)
    if sessions is None:
        raise HTTPException(status_code=404, detail="project not found")
    return SessionListResponse(
        items=[
            SessionSummary(
                id=session.id,
                project_id=session.project_id,
                mode=session.mode,
                status=session.status,
                request=session.raw_request or "",
                created_at=session.created_at,
            )
            for session in sessions
        ]
    )


@app.get("/api/v1/sessions/{session_id}/versions", response_model=ImageVersionListResponse)
def list_session_versions(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> ImageVersionListResponse:
    images = services.list_image_versions_for_session(db, current_user.id, session_id)
    if images is None:
        raise HTTPException(status_code=404, detail="session not found")
    return ImageVersionListResponse(
        items=[
            ImageSummary(
                id=image.id,
                url=image.asset_uri,
                width=image.width,
                height=image.height,
                parent_image_id=image.parent_image_id,
            )
            for image in images
        ]
    )


@app.post("/api/v1/tasks", response_model=TaskSummary, status_code=202)
def create_task(
    payload: CreateTaskRequest,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> TaskSummary:
    try:
        created = services.create_task(
            db,
            current_user,
            request=payload.request,
            mode=payload.mode,
            project_id=payload.project_id,
            parent_version_id=payload.parent_version_id,
            parameters={
                "output_count": payload.output_count,
                "aspect_ratio": payload.aspect_ratio,
                "quality": "low",
            },
        )
    except services.ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TaskSummary(
        task_id=created.session.id,
        run_id=created.run.id,
        user_id=current_user.id,
        status=TaskStatus(created.session.status),
        request=created.session.raw_request or "",
        mode=created.session.mode,
        output_count=payload.output_count,
        aspect_ratio=payload.aspect_ratio,
        parent_image_id=(created.run.parameters_json or {}).get("parent_image_id"),
        parent_run_id=created.run.parent_run_id,
    )


def _image_summaries(db: OrmSession, run_id: str) -> list[ImageSummary]:
    rows = db.scalars(select(ImageVersion).where(ImageVersion.run_id == run_id).order_by(ImageVersion.created_at)).all()
    return [
        ImageSummary(
            id=image.id,
            url=image.asset_uri,
            width=image.width,
            height=image.height,
            parent_image_id=image.parent_image_id,
        )
        for image in rows
    ]


@app.post("/api/v1/tasks/{task_id}/generate", response_model=GenerateResponse)
def generate_task(
    task_id: str,
    payload: GenerateRequest | None = Body(default=None),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
    provider: MaizitechImageProvider = Depends(get_image_provider),
) -> GenerateResponse:
    task = services.get_task_for_user(db, current_user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    parameters = services.generation_parameters(task, payload.model_dump() if payload else None)
    try:
        claimed = services.claim_generation(
            db,
            task,
            user_id=current_user.id,
            idempotency_key=idempotency_key,
            parameters=parameters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="idempotency_key_reused") from exc
    if claimed.run.status == "completed":
        images = list(
            db.scalars(
                select(ImageVersion).where(ImageVersion.run_id == claimed.run.id).order_by(ImageVersion.created_at)
            )
        )
    elif claimed.run.status in {"generating", "unknown"}:
        return GenerateResponse(
            task_id=claimed.session.id,
            status=TaskStatus.GENERATING if claimed.run.status == "generating" else TaskStatus.UNKNOWN,
            run_id=claimed.run.id,
            parent_run_id=claimed.run.parent_run_id,
            images=[],
        )
    else:
        claimed.run.parameters_json = parameters
        images = services.execute_generation(db, claimed, provider)
    db.commit()
    return GenerateResponse(
        task_id=claimed.session.id,
        status=TaskStatus(claimed.session.status),
        run_id=claimed.run.id,
        parent_run_id=claimed.run.parent_run_id,
        images=[
            ImageSummary(
                id=image.id,
                url=image.asset_uri,
                width=image.width,
                height=image.height,
                parent_image_id=image.parent_image_id,
            )
            for image in images
        ],
    )


@app.post("/api/v1/tasks/{task_id}/retry", response_model=GenerateResponse)
def retry_task(
    task_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
    provider: MaizitechImageProvider = Depends(get_image_provider),
) -> GenerateResponse:
    task = services.get_latest_task_for_user(db, current_user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    try:
        retried = services.retry_failed_generation(
            db, task, user_id=current_user.id, idempotency_key=idempotency_key
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    images = services.execute_generation(db, retried, provider)
    return GenerateResponse(
        task_id=retried.session.id,
        status=TaskStatus(retried.session.status),
        run_id=retried.run.id,
        parent_run_id=retried.run.parent_run_id,
        images=[
            ImageSummary(
                id=image.id,
                url=image.asset_uri,
                width=image.width,
                height=image.height,
                parent_image_id=image.parent_image_id,
            )
            for image in images
        ],
    )


@app.get("/api/v1/tasks/{task_id}", response_model=TaskDetail)
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> TaskDetail:
    task = services.get_task_for_user(db, current_user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    params = task.run.parameters_json or {}
    return TaskDetail(
        task_id=task.session.id,
        status=TaskStatus(task.session.status),
        mode=task.session.mode,
        request=task.session.raw_request or "",
        run_id=task.run.id,
        parent_run_id=task.run.parent_run_id,
        strategy_version=task.run.strategy_version,
        output_count=params.get("output_count"),
        aspect_ratio=params.get("aspect_ratio"),
        created_at=task.session.created_at,
        images=_image_summaries(db, task.run.id),
    )


@app.post(
    "/api/v1/tasks/{task_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_feedback(
    task_id: str,
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> FeedbackResponse:
    event_type = "selected" if payload.selected else "rejected"
    try:
        event = services.record_feedback_event(
            db,
            user=current_user,
            task_id=task_id,
            image_version_id=payload.version_id,
            event_type=event_type,
            payload={
                "selected": bool(payload.selected),
                "rejected": bool(payload.rejected),
                "rejection_reason": payload.rejection_reason,
                "direction": payload.continue_direction,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FeedbackResponse(
        event_id=event.id,
        task_id=task_id,
        version_id=payload.version_id,
        event_type=event.event_type,
    )


@app.get("/api/v1/preferences", response_model=PreferenceListResponse)
def get_preferences(
    scope: str = Query(..., pattern="^(project|session|user)$"),
    task_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> PreferenceListResponse:
    try:
        projected = services.project_preferences_for_task(
            db,
            user_id=current_user.id,
            task_id=task_id,
            scope=scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return PreferenceListResponse(
        items=[
            PreferenceView(
                key=item.key,
                value=item.value,
                source=item.source,
                confidence=item.weight,
                scope=item.scope,
                scope_id=item.scope_id,
                evidence_count=item.evidence_count,
            )
            for item in projected
        ]
    )


@app.get("/api/v1/tasks/{task_id}/runtime", response_model=TaskRuntimeResponse)
def task_runtime(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> TaskRuntimeResponse:
    projection = services.get_runtime_projection_for_user(db, current_user.id, task_id)
    if projection is None:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskRuntimeResponse(
        task_id=projection.task_id,
        state=TaskStatus(projection.state),
        session_status=projection.session_status,
        generation_status=projection.generation_status,
        retry_count=projection.retry_count,
        max_retries=projection.max_retries,
        correlation_id=projection.correlation_id,
        event_count=projection.event_count,
    )


__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
