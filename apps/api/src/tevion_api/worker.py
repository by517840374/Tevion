"""One-shot durable generation worker entrypoint.

The worker deliberately processes one leased job per invocation. A supervisor,
cron, or queue runner may call it repeatedly without making retry or scheduling
policy part of the API process.
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy.orm import Session

from .execution_jobs import GenerationExecutionAction, GenerationExecutionJobStore
from .models import GenerationRun
from .provider import ImageGenerationProvider
from .services import execute_generation, get_task_for_user, reconcile_generation


def process_one_generation_job(
    db: Session,
    provider: ImageGenerationProvider,
    *,
    worker_id: str,
    lease_seconds: int = 60,
) -> int:
    """Claim and process at most one persisted generation job."""
    store = GenerationExecutionJobStore(db)
    lease = store.claim(worker_id, lease_seconds=lease_seconds)
    if lease is None:
        return 0

    try:
        run = db.get(GenerationRun, lease.generation_run_id)
        if run is None or not run.user_id:
            raise ValueError("generation run owner is unavailable")
        task = get_task_for_user(db, run.user_id, run.session_id)
        if task is None:
            raise ValueError("generation task is unavailable")

        if lease.action in {
            GenerationExecutionAction.POLL,
            GenerationExecutionAction.RESUME,
            GenerationExecutionAction.RECONCILE,
        }:
            reconcile_generation(
                db,
                task,
                user_id=run.user_id,
                provider=provider,
                reason=f"worker action={lease.action.value}",
            )
        elif lease.action is GenerationExecutionAction.SUBMIT:
            execute_generation(db, task, provider)
        else:  # pragma: no cover - enum validation makes this unreachable
            raise ValueError(f"unsupported generation action: {lease.action.value}")
    except Exception as exc:  # noqa: BLE001 - defer keeps the job inspectable
        store.defer(lease.id, worker_id, lease.lease_epoch, error=str(exc)[:2000])
    else:
        if task.run.status in {"generating", "unknown"} and task.run.reconciliation_required:
            store.defer(
                lease.id,
                worker_id,
                lease.lease_epoch,
                delay_seconds=60,
                error="provider outcome remains pending; poll scheduled",
            )
            return 1
        store.ack(lease.id, worker_id, lease.lease_epoch)
    return 1


def worker_id_from_environment() -> str:
    return os.environ.get("TEVION_WORKER_ID") or f"worker-{uuid.uuid4().hex[:12]}"


__all__ = ["process_one_generation_job", "worker_id_from_environment"]
