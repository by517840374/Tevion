import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from .learning import FeedbackEvidence, PreferenceProjector, ProjectedPreference
from .models import (
    FeedbackEvent,
    GenerationRun,
    ImageVersion,
    PreferenceEvent,
    Project,
    Session,
    User,
)
from .provider import (
    GenerationRequest,
    GenerationResult,
    ImageGenerationProvider,
    ProviderResponseError,
    classify_provider_error,
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


@dataclass(frozen=True)
class TaskRuntimeProjection:
    task_id: str
    state: str
    session_status: str
    generation_status: str
    retry_count: int = 0
    max_retries: int = 2
    event_count: int = 0

    @property
    def correlation_id(self) -> str:
        return self.task_id


class ProjectNotFoundError(ValueError):
    """Raised when a requested project is not owned by the current user."""


def _resolve_project(db: OrmSession, user: User, project_id: str | None) -> Project:
    if project_id is None:
        project = db.scalar(select(Project).where(Project.user_id == user.id).order_by(Project.created_at).limit(1))
        if project is None:
            project = Project(user_id=user.id, name="默认项目")
            db.add(project)
            db.flush()
        return project

    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user.id))
    if project is None:
        # Do not reveal whether an id belongs to another user or exists at all.
        raise ProjectNotFoundError("project not found")
    return project


def create_task(
    db: OrmSession,
    user: User,
    *,
    request: str,
    mode: str,
    parameters: dict | None = None,
    strategy_version: str = "default",
    parent_version_id: str | None = None,
    project_id: str | None = None,
) -> CreatedTask:
    project = _resolve_project(db, user, project_id)
    parent_run_id = None
    if mode == "refine":
        if not parent_version_id:
            raise ValueError("parent image is required for refine")
        parent = db.scalar(
            select(ImageVersion)
            .join(GenerationRun, ImageVersion.run_id == GenerationRun.id)
            .join(Session, GenerationRun.session_id == Session.id)
            .join(Project, Session.project_id == Project.id)
            .where(
                ImageVersion.id == parent_version_id,
                Session.project_id == project.id,
                Project.user_id == user.id,
            )
        )
        if parent is None:
            raise ValueError("parent image not found")
        parent_run_id = parent.run_id
        parameters = {**(parameters or {}), "parent_image_id": parent.id}
    session = Session(project_id=project.id, mode=mode, raw_request=request, status="created")
    db.add(session)
    db.flush()
    run = GenerationRun(
        session_id=session.id,
        user_id=user.id,
        parent_run_id=parent_run_id,
        strategy_version=strategy_version,
        status="created",
        parameters_json=parameters,
    )
    db.add(run)
    db.commit()
    db.refresh(session)
    db.refresh(run)
    return CreatedTask(session=session, run=run)


def generation_parameters(task: CreatedTask, overrides: dict | None = None) -> dict:
    params = dict(task.run.parameters_json or {})
    params.update({key: value for key, value in (overrides or {}).items() if value is not None})
    return params


def claim_generation(
    db: OrmSession,
    task: CreatedTask,
    *,
    user_id: str,
    idempotency_key: str | None,
    parameters: dict,
) -> CreatedTask:
    if idempotency_key is None:
        task.run.parameters_json = parameters
        db.commit()
        return task
    fingerprint = hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    existing = db.scalar(
        select(GenerationRun).where(
            GenerationRun.user_id == user_id,
            GenerationRun.session_id == task.session.id,
            GenerationRun.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ValueError("idempotency_key_reused")
        return CreatedTask(task.session, existing)
    if task.run.idempotency_key is None and task.run.status == "created":
        task.run.idempotency_key = idempotency_key
        task.run.request_fingerprint = fingerprint
        task.run.parameters_json = parameters
        db.commit()
        return task
    run = GenerationRun(
        session_id=task.session.id,
        user_id=user_id,
        parent_run_id=task.run.parent_run_id,
        strategy_version=task.run.strategy_version,
        status="created",
        parameters_json=parameters,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
    )
    db.add(run)
    try:
        db.commit()
        db.refresh(run)
        return CreatedTask(task.session, run)
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(GenerationRun).where(
                GenerationRun.user_id == user_id,
                GenerationRun.session_id == task.session.id,
                GenerationRun.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        if existing.request_fingerprint != fingerprint:
            raise ValueError("idempotency_key_reused")
        return CreatedTask(task.session, existing)


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


def get_latest_task_for_user(db: OrmSession, user_id: str, task_id: str) -> CreatedTask | None:
    row = db.execute(
        select(Session, GenerationRun)
        .join(Project, Session.project_id == Project.id)
        .join(GenerationRun, GenerationRun.session_id == Session.id)
        .where(Session.id == task_id, Project.user_id == user_id)
        .order_by(GenerationRun.started_at.desc().nullslast(), GenerationRun.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    session, run = row
    return CreatedTask(session=session, run=run)


def retry_failed_generation(
    db: OrmSession,
    task: CreatedTask,
    *,
    user_id: str,
    idempotency_key: str | None,
) -> CreatedTask:
    parameters = dict(task.run.parameters_json or {})
    fingerprint = hashlib.sha256(json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if idempotency_key is not None:
        existing = db.scalar(
            select(GenerationRun).where(
                GenerationRun.user_id == user_id,
                GenerationRun.session_id == task.session.id,
                GenerationRun.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ValueError("idempotency_key_reused")
            return CreatedTask(task.session, existing)
    if task.run.status != "failed":
        raise ValueError("only failed generation runs can be retried")
    run = GenerationRun(
        session_id=task.session.id,
        user_id=user_id,
        parent_run_id=task.run.id,
        strategy_version=task.run.strategy_version,
        status="created",
        parameters_json=parameters,
    )
    if idempotency_key is not None:
        run.idempotency_key = idempotency_key
        run.request_fingerprint = fingerprint
    db.add(run)
    db.commit()
    db.refresh(run)
    return CreatedTask(task.session, run)


def get_runtime_projection_for_user(db: OrmSession, user_id: str, task_id: str) -> TaskRuntimeProjection | None:
    """Read the owner task and project its committed task/attempt statuses."""
    session = db.scalar(
        select(Session)
        .join(Project, Session.project_id == Project.id)
        .where(Session.id == task_id, Project.user_id == user_id)
    )
    if session is None:
        return None
    run = db.scalar(
        select(GenerationRun)
        .where(GenerationRun.session_id == session.id)
        .order_by(GenerationRun.started_at.desc().nullslast(), GenerationRun.id.desc())
        .limit(1)
    )
    generation_status = run.status if run is not None else "created"
    if generation_status in {"generating", "unknown"}:
        state = "recovery_required"
    elif generation_status == "failed":
        state = "needs_user_review"
    else:
        state = session.status
    return TaskRuntimeProjection(
        task_id=session.id,
        state=state,
        session_status=session.status,
        generation_status=generation_status,
    )


def list_projects_for_user(db: OrmSession, user_id: str) -> list[Project]:
    return list(db.scalars(select(Project).where(Project.user_id == user_id).order_by(Project.created_at, Project.id)))


def list_sessions_for_project(db: OrmSession, user_id: str, project_id: str) -> list[Session] | None:
    project = db.scalar(select(Project).where(Project.id == project_id, Project.user_id == user_id))
    if project is None:
        return None
    return list(
        db.scalars(select(Session).where(Session.project_id == project_id).order_by(Session.created_at, Session.id))
    )


def list_image_versions_for_session(db: OrmSession, user_id: str, session_id: str) -> list[ImageVersion] | None:
    owned_session = db.scalar(
        select(Session)
        .join(Project, Session.project_id == Project.id)
        .where(Session.id == session_id, Project.user_id == user_id)
    )
    if owned_session is None:
        return None
    return list(
        db.scalars(
            select(ImageVersion)
            .join(GenerationRun, ImageVersion.run_id == GenerationRun.id)
            .where(GenerationRun.session_id == session_id)
            .order_by(ImageVersion.created_at, ImageVersion.id)
        )
    )


def get_image_version_for_user(
    db: OrmSession, user_id: str, task_id: str, image_version_id: str
) -> OwnedImageVersion | None:
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


def project_preferences_for_task(
    db: OrmSession, *, user_id: str, task_id: str, scope: str
) -> list[ProjectedPreference]:
    task = get_task_for_user(db, user_id, task_id)
    if task is None:
        raise ValueError("task not found")

    events = list_feedback_events_for_task(db, user_id=user_id, task_id=task_id)
    evidence: list[FeedbackEvidence] = []
    for event in events:
        evidence.extend(_feedback_to_evidence(event, project_id=task.session.project_id))

    scope_id = task.session.project_id if scope == "project" else task.session.id if scope == "session" else None
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


def _redact_metadata_value(value: object, blocked_keys: set[str]) -> object:
    if isinstance(value, dict):
        return {
            key: _redact_metadata_value(item, blocked_keys)
            for key, item in value.items()
            if isinstance(key, str) and key.lower() not in blocked_keys
        }
    if isinstance(value, list):
        return [_redact_metadata_value(item, blocked_keys) for item in value]
    return value


def _safe_result_metadata(result: GenerationResult) -> dict:
    metadata = result.metadata or {}
    blocked_keys = {"api_key", "authorization", "headers", "raw_response", "private_image", "provider"}
    redacted = _redact_metadata_value(metadata, blocked_keys)
    return redacted if isinstance(redacted, dict) else {}


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
    if run.status == "completed":
        return list(
            db.scalars(select(ImageVersion).where(ImageVersion.run_id == run.id).order_by(ImageVersion.created_at))
        )
    if run.status in {"generating", "unknown"}:
        return []
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
        classification = classify_provider_error(exc)
        if classification.code == "timeout":
            run.status = "unknown"
            run.error_code = "provider_timeout_unknown"
            run.error_message = "provider request outcome is unknown; recovery required"
        else:
            run.status = "failed"
            run.error_code = classification.code
            run.error_message = str(exc)[:2000] if classification.code == "provider_error" else classification.message
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001 - record any provider failure
        run.status = "failed"
        run.error_code = "internal"
        run.error_message = str(exc)[:2000]
        db.commit()
        raise

    images: list[ImageVersion] = []
    metadata = _safe_result_metadata(result)
    metadata["provider"] = result.provider_name
    metadata["model"] = result.model_name
    metadata["provider_request_id"] = result.provider_request_id
    metadata["metadata_source"] = result.metadata_source
    width, height = _parse_pixel_size(metadata.get("size"))
    for asset_uri in result.asset_urls:
        image = ImageVersion(
            run_id=run.id,
            parent_image_id=parameters.get("parent_image_id"),
            asset_uri=asset_uri,
            width=width,
            height=height,
            prompt=request.prompt,
            metadata_json=metadata,
        )
        db.add(image)
        images.append(image)

    run.status = "completed"
    run.provider_name = result.provider_name
    run.provider_request_id = result.provider_request_id or None
    run.model_name = result.model_name
    run.latency_ms = result.latency_ms
    run.estimated_cost = result.cost
    run.completed_at = datetime.now(timezone.utc)
    session.status = "awaiting_selection"
    db.commit()
    for image in images:
        db.refresh(image)
    return images
