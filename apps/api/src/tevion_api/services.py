"""Task service: persistence boundary between the API and ORM models.

A "task" maps to one Session plus its initial GenerationRun. The session owns
the product conversation (mode, raw request); the run owns one generation
attempt (strategy version, provider, cost). Both rows are created together so
the task is reconstructable from day one.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .models import GenerationRun, ImageVersion, Project, Session, User
from .provider import GenerationRequest, GenerationResult, ImageGenerationProvider


@dataclass(frozen=True)
class CreatedTask:
    session: Session
    run: GenerationRun


def _ensure_default_project(db: OrmSession, user: User) -> Project:
    project = db.scalar(
        select(Project).where(Project.user_id == user.id).order_by(Project.created_at).limit(1)
    )
    if project is None:
        project = Project(user_id=user.id, name="默认项目")
        db.add(project)
        db.flush()
    return project


def create_task(
    db: OrmSession,
    user: User,
    *,
    request: str,
    mode: str,
    parameters: dict | None = None,
    strategy_version: str = "default",
) -> CreatedTask:
    project = _ensure_default_project(db, user)
    session = Session(project_id=project.id, mode=mode, raw_request=request, status="created")
    db.add(session)
    db.flush()
    run = GenerationRun(
        session_id=session.id,
        strategy_version=strategy_version,
        status="created",
        parameters_json=parameters,
    )
    db.add(run)
    db.commit()
    db.refresh(session)
    db.refresh(run)
    return CreatedTask(session=session, run=run)


def get_task_for_user(db: OrmSession, user_id: str, task_id: str) -> CreatedTask | None:
    """Return the task only when it belongs to the given user (ownership check)."""
    row = db.execute(
        select(Session, GenerationRun)
        .join(Project, Session.project_id == Project.id)
        .join(GenerationRun, GenerationRun.session_id == Session.id)
        .where(
            Session.id == task_id,
            Project.user_id == user_id,
        )
        .order_by(GenerationRun.started_at)
        .limit(1)
    ).first()
    if row is None:
        return None
    session, run = row
    return CreatedTask(session=session, run=run)


def _parse_pixel_size(size: str | None) -> tuple[int | None, int | None]:
    if not size or "x" not in size:
        return None, None
    parts = size.lower().split("x")
    if len(parts) != 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def execute_generation(
    db: OrmSession,
    task: CreatedTask,
    provider: ImageGenerationProvider,
) -> list[ImageVersion]:
    """Run one real generation and persist every output image version.

    Mutates run and session status along the way; caller commits.
    """
    session, run = task.session, task.run
    parameters = run.parameters_json or {}
    now = datetime.now(timezone.utc)

    run.status = "generating"
    run.started_at = now
    db.flush()

    request = GenerationRequest(
        prompt=session.raw_request or "",
        output_count=int(parameters.get("output_count") or 1),
        aspect_ratio=str(parameters.get("aspect_ratio") or "1:1"),
        quality=str(parameters.get("quality") or "low"),
    )
    result: GenerationResult = provider.generate(request)

    images: list[ImageVersion] = []
    width, height = _parse_pixel_size((result.metadata or {}).get("size"))
    for asset_uri in result.asset_urls:
        image = ImageVersion(
            run_id=run.id,
            asset_uri=asset_uri,
            width=width,
            height=height,
            prompt=request.prompt,
            metadata_json={"model": result.model_name, "provider": "maizitech"},
        )
        db.add(image)
        images.append(image)

    run.status = "completed"
    run.model_name = result.model_name
    run.latency_ms = result.latency_ms
    run.estimated_cost = result.cost
    run.completed_at = datetime.now(timezone.utc)
    session.status = "awaiting_selection"
    db.flush()
    for image in images:
        db.refresh(image)
    return images
