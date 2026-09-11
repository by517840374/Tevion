import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tevion_api.db import Base
from tevion_api.execution_jobs import (
    GenerationExecutionAction,
    GenerationExecutionJobStore,
    GenerationLifecycleAdapter,
)
from tevion_api.worker import process_one_generation_job
from tevion_api import services
from tevion_api.models import GenerationRun, Project, User
from tevion_api.models import Session as GenerationSession
from tevion_api.provider import ProviderOperationResult, ProviderOperationStatus

TEST_DB_URL = os.environ.get("TEVION_TEST_DB_URL", "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test")


def test_enqueue_is_idempotent_per_invocation_and_action(db):
    store = GenerationExecutionJobStore(db)
    run_id = db.query(GenerationRun).one().id
    first = store.enqueue(run_id, "invocation-1", GenerationExecutionAction.RESUME)
    second = store.enqueue(run_id, "invocation-1", "resume")
    assert first.id == second.id


def test_claim_is_atomic_and_epoch_fences_ack(db):
    store = GenerationExecutionJobStore(db)
    run_id = db.query(GenerationRun).one().id
    store.enqueue(run_id, "invocation-2", "poll")
    lease_a = store.claim("worker-a", lease_seconds=30)
    assert lease_a is not None
    assert store.claim("worker-b", lease_seconds=30) is None
    assert store.ack(lease_a.id, "worker-a", lease_a.lease_epoch) is True
    assert store.ack(lease_a.id, "worker-b", lease_a.lease_epoch) is False


def test_renew_changes_epoch_and_stale_ack_is_rejected(db):
    store = GenerationExecutionJobStore(db)
    run_id = db.query(GenerationRun).one().id
    store.enqueue(run_id, "invocation-3", "poll")
    lease = store.claim("worker-a", lease_seconds=1)
    assert lease is not None
    renewed = store.renew(lease.id, "worker-a", lease.lease_epoch, lease_seconds=30)
    assert renewed.lease_epoch == lease.lease_epoch + 1
    assert store.ack(lease.id, "worker-a", lease.lease_epoch) is False
    assert store.ack(lease.id, "worker-a", renewed.lease_epoch) is True


def test_defer_reschedules_without_automatic_retry(db):
    store = GenerationExecutionJobStore(db)
    run_id = db.query(GenerationRun).one().id
    store.enqueue(run_id, "invocation-4", "reconcile")
    lease = store.claim("worker-a", lease_seconds=30)
    assert lease is not None
    deferred = store.defer(lease.id, "worker-a", lease.lease_epoch, delay_seconds=45)
    assert deferred.status == "deferred"
    assert deferred.available_at > datetime.now(timezone.utc) + timedelta(seconds=40)


def test_lifecycle_known_id_enqueues_resume_poll_and_unknown_requires_reconciliation(db):
    store = GenerationExecutionJobStore(db)
    adapter = GenerationLifecycleAdapter(store)
    run_id = db.query(GenerationRun).one().id
    known = adapter.on_generation_started(run_id, "inv-known", provider_request_id="provider-1")
    unknown = adapter.on_generation_started(run_id, "inv-unknown", provider_request_id=None)
    assert [job.action for job in known] == [GenerationExecutionAction.RESUME, GenerationExecutionAction.POLL]
    assert unknown == []
    assert adapter.reconciliation_required(run_id) is True


def test_run_once_is_bounded_and_uses_handler(db):
    store = GenerationExecutionJobStore(db)
    run_id = db.query(GenerationRun).one().id
    store.enqueue(run_id, "invocation-5", "poll")
    seen = []
    adapter = GenerationLifecycleAdapter(store)
    processed = adapter.run_once("worker-a", lambda job: seen.append(job.action))
    assert processed == 1
    assert seen == [GenerationExecutionAction.POLL]
    assert store.claim("worker-b") is None


def test_expired_claim_can_be_reclaimed_with_a_new_epoch(db):
    store = GenerationExecutionJobStore(db)
    run_id = db.query(GenerationRun).one().id
    store.enqueue(run_id, "invocation-expired", "poll")

    first = store.claim("worker-a", lease_seconds=0)
    assert first is not None
    second = store.claim("worker-b", lease_seconds=30)

    assert second is not None
    assert second.id == first.id
    assert second.lease_epoch > first.lease_epoch


def test_worker_processes_persisted_resume_job_without_submitting_again(db):
    task = services.CreatedTask(db.query(GenerationSession).one(), db.query(GenerationRun).one())
    task.run.user_id = db.query(User).one().id
    task.run.status = "unknown"
    task.run.provider_request_id = "provider-request-worker"
    task.run.reconciliation_required = True
    db.commit()

    store = GenerationExecutionJobStore(db)
    job = store.enqueue(task.run.id, "invocation-worker", GenerationExecutionAction.RESUME)

    class Provider:
        def __init__(self):
            self.resume_calls = []
            self.submit_calls = 0

        def resume(self, request_id):
            self.resume_calls.append(request_id)
            return ProviderOperationResult(ProviderOperationStatus.PENDING, request_id)

        def submit(self, request):
            self.submit_calls += 1
            raise AssertionError("worker must not submit a second provider request")

    provider = Provider()
    assert process_one_generation_job(db, provider, worker_id="worker-test") == 1
    db.refresh(job)
    assert job.status == "deferred", job.last_error
    assert provider.resume_calls == ["provider-request-worker"]
    assert provider.submit_calls == 0


@pytest.fixture()
def db():
    try:
        engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except Exception:
        pytest.skip("PostgreSQL unavailable")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(auth_provider="oidc", provider_subject=f"issue88-{uuid.uuid4().hex}")
        project = Project(user=user, name="issue88")
        generation_session = GenerationSession(project=project, mode="explore")
        run = GenerationRun(session=generation_session, user_id=user.id, status="created")
        session.add(run)
        session.commit()
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()
