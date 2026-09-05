"""Durable, queue-independent generation execution jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import GenerationExecutionJob, GenerationRun


class GenerationExecutionAction(StrEnum):
    SUBMIT = "submit"
    POLL = "poll"
    RESUME = "resume"
    RECONCILE = "reconcile"


class JobLeaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobLease:
    id: str
    generation_run_id: str
    invocation_id: str
    action: GenerationExecutionAction
    lease_epoch: int


class GenerationExecutionJobStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def enqueue(self, generation_run_id: str, invocation_id: str, action: str | GenerationExecutionAction) -> GenerationExecutionJob:
        action = GenerationExecutionAction(action)
        existing = self.db.scalar(select(GenerationExecutionJob).where(
            GenerationExecutionJob.generation_run_id == generation_run_id,
            GenerationExecutionJob.invocation_id == invocation_id,
            GenerationExecutionJob.action == action.value,
        ))
        if existing is not None:
            return existing
        job = GenerationExecutionJob(generation_run_id=generation_run_id, invocation_id=invocation_id, action=action.value)
        self.db.add(job)
        try:
            self.db.commit()
            self.db.refresh(job)
            return job
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(select(GenerationExecutionJob).where(
                GenerationExecutionJob.generation_run_id == generation_run_id,
                GenerationExecutionJob.invocation_id == invocation_id,
                GenerationExecutionJob.action == action.value,
            ))
            if existing is None:
                raise RuntimeError("job disappeared after unique conflict")
            return existing

    def claim(self, worker_id: str, *, lease_seconds: int = 60) -> JobLease | None:
        now = datetime.now(timezone.utc)
        job = self.db.scalar(select(GenerationExecutionJob).where(
            GenerationExecutionJob.status.in_(["queued", "deferred"]),
            GenerationExecutionJob.available_at <= now,
        ).order_by(GenerationExecutionJob.created_at, GenerationExecutionJob.id).with_for_update(skip_locked=True).limit(1))
        if job is None:
            self.db.rollback()
            return None
        job.status = "claimed"
        job.claimed_by = worker_id
        job.lease_expires_at = now + timedelta(seconds=lease_seconds)
        job.lease_epoch += 1
        self.db.commit()
        return JobLease(job.id, job.generation_run_id, job.invocation_id, GenerationExecutionAction(job.action), job.lease_epoch)

    def _owned(self, job_id: str, worker_id: str, epoch: int) -> GenerationExecutionJob | None:
        now = datetime.now(timezone.utc)
        return self.db.scalar(select(GenerationExecutionJob).where(
            GenerationExecutionJob.id == job_id,
            GenerationExecutionJob.claimed_by == worker_id,
            GenerationExecutionJob.lease_epoch == epoch,
            GenerationExecutionJob.status == "claimed",
            GenerationExecutionJob.lease_expires_at > now,
        ).with_for_update())

    def renew(self, job_id: str, worker_id: str, epoch: int, *, lease_seconds: int = 60) -> JobLease:
        job = self._owned(job_id, worker_id, epoch)
        if job is None:
            self.db.rollback()
            raise JobLeaseError("lease is not current")
        job.lease_epoch += 1
        job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        self.db.commit()
        return JobLease(job.id, job.generation_run_id, job.invocation_id, GenerationExecutionAction(job.action), job.lease_epoch)

    def ack(self, job_id: str, worker_id: str, epoch: int) -> bool:
        job = self._owned(job_id, worker_id, epoch)
        if job is None:
            self.db.rollback()
            return False
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.claimed_by = None
        job.lease_expires_at = None
        self.db.commit()
        return True

    def defer(self, job_id: str, worker_id: str, epoch: int, *, delay_seconds: int = 60, error: str | None = None) -> GenerationExecutionJob:
        job = self._owned(job_id, worker_id, epoch)
        if job is None:
            self.db.rollback()
            raise JobLeaseError("lease is not current")
        job.status = "deferred"
        job.available_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        job.last_error = error
        job.claimed_by = None
        job.lease_expires_at = None
        self.db.commit()
        return job


class GenerationLifecycleAdapter:
    def __init__(self, store: GenerationExecutionJobStore) -> None:
        self.store = store

    def on_generation_started(self, run_id: str, invocation_id: str, *, provider_request_id: str | None) -> list[GenerationExecutionJob]:
        run = self.store.db.get(GenerationRun, run_id)
        if run is None:
            raise ValueError("generation run not found")
        if provider_request_id:
            return [self.store.enqueue(run_id, invocation_id, action) for action in (GenerationExecutionAction.RESUME, GenerationExecutionAction.POLL)]
        run.reconciliation_required = True
        run.reconciliation_reason = "provider correlation unavailable; manual reconciliation required"
        self.store.db.commit()
        return []

    def reconciliation_required(self, run_id: str) -> bool:
        run = self.store.db.get(GenerationRun, run_id)
        return bool(run and run.reconciliation_required)

    def run_once(self, worker_id: str, handler: Callable[[JobLease], object], *, lease_seconds: int = 60) -> int:
        lease = self.store.claim(worker_id, lease_seconds=lease_seconds)
        if lease is None:
            return 0
        try:
            handler(lease)
        except Exception as exc:
            self.store.defer(lease.id, worker_id, lease.lease_epoch, error=str(exc))
        else:
            self.store.ack(lease.id, worker_id, lease.lease_epoch)
        return 1


def enqueue_generation_action(db: Session, run_id: str, invocation_id: str, action: str | GenerationExecutionAction) -> GenerationExecutionJob:
    return GenerationExecutionJobStore(db).enqueue(run_id, invocation_id, action)


def enqueue_lifecycle_jobs(db: Session, run_id: str, invocation_id: str, provider_request_id: str | None) -> list[GenerationExecutionJob]:
    return GenerationLifecycleAdapter(GenerationExecutionJobStore(db)).on_generation_started(run_id, invocation_id, provider_request_id=provider_request_id)


def _claim_row(db: Session, worker_id: str, lease_seconds: int = 60) -> JobLease | None:
    return GenerationExecutionJobStore(db).claim(worker_id, lease_seconds=lease_seconds)


def _ensure_valid_action(action: str) -> GenerationExecutionAction:
    return GenerationExecutionAction(action)


def _job_now() -> datetime:
    return datetime.now(timezone.utc)


def _lease_deadline(seconds: int) -> datetime:
    return _job_now() + timedelta(seconds=seconds)


def _load_job(db: Session, job_id: str) -> GenerationExecutionJob | None:
    return db.get(GenerationExecutionJob, job_id)


def _load_run(db: Session, run_id: str) -> GenerationRun | None:
    return db.get(GenerationRun, run_id)


def _is_known_provider_id(provider_request_id: str | None) -> bool:
    return bool(provider_request_id)


def _mark_reconciliation_required(db: Session, run_id: str, reason: str) -> None:
    run = _load_run(db, run_id)
    if run is not None:
        run.reconciliation_required = True
        run.reconciliation_reason = reason
        db.commit()


def _unused_helpers_are_intentional() -> None:
    """Keep action and clock semantics named for adapters without a queue dependency."""
    return None


__all__ = [
    "GenerationExecutionAction", "GenerationExecutionJobStore", "GenerationLifecycleAdapter",
    "JobLease", "JobLeaseError", "enqueue_generation_action", "enqueue_lifecycle_jobs",
]
