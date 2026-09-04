from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .learning import FeedbackEvidence, PreferenceProjector, ProjectedPreference
from .models import FeedbackEvent, GenerationRun, ImageVersion, PreferenceEvent, Project, Session, User
from .provider import (
    GenerationRequest,
    GenerationResult,
    ImageGenerationProvider,
    ProviderResponseError,
)


@dataclass(frozen=True)
class CreatedTask:
    session: Session
    run: GenerationRun


@dataclass(frozen=True)
class OwnedImageVersion:
    session: Session
    run: GenerationRun
    image: ImageVersion


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


def get_image_version_for_user(db: OrmSession, user_id: str, task_id: str, image_version_id: str) -> OwnedImageVersion | None:
    row = db.execute(
        select(Session, GenerationRun, ImageVersion)
        .join(Project, Session.project_id == Project.id)
        .join(GenerationRun, GenerationRun.session_id == Session.id)
        .join(ImageVersion, ImageVersion.run_id == GenerationRun.id)
        .where(
            Session.id == task_id,
            Project.user_id == user_id,
            ImageVersion.id == image_version_id,
        )
        .limit(1)
    ).first()
    if row is None:
        return None
    session, run, image = row
    return OwnedImageVersion(session=session, run=run, image=image)


def record_feedback_event(
    db: OrmSession,
    *,
    user: User,
    task_id: str,
    image_version_id: str,
    event_type: str,
    payload: dict,
) -> FeedbackEvent:
    owned = get_image_version_for_user(db, user.id, task_id, image_version_id)
    if owned is None:
        raise ValueError("task or image not found")

    event = FeedbackEvent(
        user_id=user.id,
        session_id=owned.session.id,
        image_version_id=owned.image.id,
        event_type=event_type,
        payload_json=payload,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_feedback_events_for_task(db: OrmSession, *, user_id: str, task_id: str) -> list[FeedbackEvent]:
    return list(
        db.scalars(
            select(FeedbackEvent)
            .join(Session, FeedbackEvent.session_id == Session.id)
            .join(Project, Session.project_id == Project.id)
            .where(
                FeedbackEvent.session_id == task_id,
                Project.user_id == user_id,
            )
            .order_by(FeedbackEvent.created_at, FeedbackEvent.id)
        )
    )


def _feedback_to_evidence(feedback: FeedbackEvent, *, project_id: str) -> list[FeedbackEvidence]:
    payload = feedback.payload_json or {}
    evidences: list[FeedbackEvidence] = []

    direction = payload.get("direction")
    if isinstance(direction, str) and direction.strip():
        evidences.append(
            FeedbackEvidence(
                scope="session",
                scope_id=feedback.session_id,
                key="direction",
                value=direction.strip(),
                source="explicit_feedback",
            )
        )

    rejection_reason = payload.get("rejection_reason")
    if isinstance(rejection_reason, str) and rejection_reason.strip():
        evidences.append(
            FeedbackEvidence(
                scope="project",
                scope_id=project_id,
                key="rejection_reason",
                value=rejection_reason.strip(),
                source="tagged_feedback",
            )
        )

    selected = payload.get("selected")
    if selected is True:
        evidences.append(
            FeedbackEvidence(
                scope="project",
                scope_id=project_id,
                key="image_version_id",
                value=feedback.image_version_id,
                source="selection",
            )
        )

    return evidences


def project_preferences_for_task(db: OrmSession, *, user_id: str, task_id: str, scope: str) -> list[ProjectedPreference]:
    task = get_task_for_user(db, user_id, task_id)
    if task is None:
        raise ValueError("task not found")

    events = list_feedback_events_for_task(db, user_id=user_id, task_id=task_id)
    evidence: list[FeedbackEvidence] = []
    for event in events:
        evidence.extend(_feedback_to_evidence(event, project_id=task.session.project_id))

    scope_id = (
        task.session.project_id if scope == "project" else task.session.id if scope == "session" else None
    )
    for pref_event in db.scalars(
        select(PreferenceEvent)
        .where(
            PreferenceEvent.user_id == user_id,
            PreferenceEvent.scope == scope,
            PreferenceEvent.scope_id == scope_id,
        )
        .order_by(PreferenceEvent.created_at, PreferenceEvent.id)
    ):
        evidence.append(
            FeedbackEvidence(
                scope=pref_event.scope,
                scope_id=pref_event.scope_id,
                key=pref_event.key,
                value=pref_event.value,
                source=pref_event.source,
                deleted=pref_event.deleted,
            )
        )

    projected = PreferenceProjector().project(evidence)
    return [item for item in projected if item.scope == scope]


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

    Mutates run and session status; failure is recorded on the run and
    re-raised so the API can map it to an HTTP error.
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
    try:
        result: GenerationResult = provider.generate(request)
    except ProviderResponseError as exc:
        run.status = "failed"
        run.error_code = "provider_error"
        run.error_message = str(exc)
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001 - record any provider failure
        run.status = "failed"
        run.error_code = "internal"
        run.error_message = str(exc)[:2000]
        db.commit()
        raise

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
    db.commit()
    for image in images:
        db.refresh(image)
    return images
