"""Task service: persistence boundary between the API and ORM models.

A "task" maps to one Session plus its initial GenerationRun. The session owns
the product conversation (mode, raw request); the run owns one generation
attempt (strategy version, provider, cost). Both rows are created together so
the task is reconstructable from day one.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from .models import GenerationRun, Project, Session, User


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
