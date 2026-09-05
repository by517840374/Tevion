import os
import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session as OrmSession

from tevion_api import models as m
from tevion_api import services
from tevion_api.db import Base
from tevion_api.provider import (
    GenerationRequest,
    GenerationResult,
    ProviderOperationResult,
    ProviderOperationStatus,
)

TEST_DB_URL = os.environ.get(
    "TEVION_TEST_DB_URL",
    "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test",
)


def _reachable() -> bool:
    try:
        engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="PostgreSQL unavailable")


class ReconciliationProvider:
    def __init__(self, outcome: ProviderOperationResult) -> None:
        self.outcome = outcome
        self.resume_calls: list[str] = []
        self.submit_calls = 0

    def resume(self, provider_request_id: str) -> ProviderOperationResult:
        self.resume_calls.append(provider_request_id)
        return self.outcome

    def submit(self, request: GenerationRequest) -> ProviderOperationResult:
        self.submit_calls += 1
        raise AssertionError("reconciliation must never submit a new provider request")


@pytest.fixture()
def db() -> Generator[OrmSession, None, None]:
    engine = create_engine(TEST_DB_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with OrmSession(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _task(db: OrmSession, *, user_subject: str = "issue82-owner") -> services.CreatedTask:
    user = m.User(auth_provider="oidc", provider_subject=f"{user_subject}-{uuid.uuid4().hex}")
    db.add(user)
    db.flush()
    task = services.create_task(db, user, request="portrait", mode="explore", parameters={"output_count": 1})
    task.run.status = "unknown"
    task.run.provider_request_id = "provider-request-82"
    task.run.reconciliation_required = True
    task.session.status = "generating"
    db.commit()
    return task


def _completed_result(*, request_id: str = "provider-request-82", cost: float | None = 0.02) -> GenerationResult:
    return GenerationResult(
        provider_name="fake",
        provider_request_id=request_id,
        model_name="gpt-image-2",
        asset_urls=["https://cdn.example.test/one.png"],
        latency_ms=12,
        metadata_source="provider_evidence",
        cost=cost,
        metadata={"size": "1024x1280", "private_image": "do-not-store"},
    )


def test_reconcile_completed_evidence_finalizes_one_image_and_preserves_cost(db: OrmSession) -> None:
    task = _task(db)
    provider = ReconciliationProvider(
        ProviderOperationResult(
            status=ProviderOperationStatus.COMPLETED,
            provider_request_id="provider-request-82",
            result=_completed_result(),
        )
    )

    first = services.reconcile_generation(db, task, user_id=task.run.user_id, provider=provider, reason="用户确认")
    first_cost = first.run.estimated_cost
    second = services.reconcile_generation(db, task, user_id=task.run.user_id, provider=provider, reason="重复确认")

    assert first.run.status == "completed"
    assert second.run.status == "completed"
    assert provider.resume_calls == ["provider-request-82"]
    assert provider.submit_calls == 0
    assert db.scalar(select(func.count(m.ImageVersion.id)).where(m.ImageVersion.run_id == task.run.id)) == 1
    assert first_cost == 0.02
    assert second.run.estimated_cost == first_cost
    assert "用户确认" in second.run.reconciliation_reason
    assert "one.png" not in second.run.reconciliation_reason
    assert "do-not-store" not in (second.run.image_versions[0].metadata_json or {})


def test_reconcile_failed_evidence_marks_failed_without_submitting(db: OrmSession) -> None:
    task = _task(db)
    provider = ReconciliationProvider(
        ProviderOperationResult(
            status=ProviderOperationStatus.FAILED,
            provider_request_id="provider-request-82",
            error_code="provider_cancelled",
            error_message="cancelled by provider",
        )
    )

    result = services.reconcile_generation(
        db, task, user_id=task.run.user_id, provider=provider, reason="provider 查询"
    )

    assert result.run.status == "failed"
    assert result.run.error_code == "provider_cancelled"
    assert provider.submit_calls == 0
    assert db.scalar(select(func.count(m.ImageVersion.id)).where(m.ImageVersion.run_id == task.run.id)) == 0


def test_reconcile_without_persisted_id_stays_unknown_and_never_submits(db: OrmSession) -> None:
    task = _task(db)
    task.run.provider_request_id = None
    db.commit()
    provider = ReconciliationProvider(
        ProviderOperationResult(status=ProviderOperationStatus.COMPLETED, provider_request_id=None)
    )

    result = services.reconcile_generation(
        db, task, user_id=task.run.user_id, provider=provider, reason="无 provider ID"
    )

    assert result.run.status == "unknown"
    assert result.run.reconciliation_required is True
    assert provider.resume_calls == []
    assert provider.submit_calls == 0
    assert db.scalar(select(func.count(m.ImageVersion.id)).where(m.ImageVersion.run_id == task.run.id)) == 0


def test_reconcile_conflicting_or_unknown_evidence_requires_review(db: OrmSession) -> None:
    task = _task(db)
    provider = ReconciliationProvider(
        ProviderOperationResult(
            status=ProviderOperationStatus.COMPLETED,
            provider_request_id="different-request",
            result=_completed_result(request_id="different-request"),
        )
    )

    result = services.reconcile_generation(db, task, user_id=task.run.user_id, provider=provider, reason="冲突证据")

    assert result.run.status == "needs_user_review"
    assert result.run.reconciliation_required is True
    assert "冲突" in result.run.reconciliation_reason
    assert db.scalar(select(func.count(m.ImageVersion.id)).where(m.ImageVersion.run_id == task.run.id)) == 0


def test_reconcile_is_owner_scoped(db: OrmSession) -> None:
    task = _task(db, user_subject="owner")
    intruder = m.User(auth_provider="oidc", provider_subject=f"intruder-{uuid.uuid4().hex}")
    db.add(intruder)
    db.commit()
    provider = ReconciliationProvider(
        ProviderOperationResult(status=ProviderOperationStatus.UNKNOWN, provider_request_id="provider-request-82")
    )

    assert services.reconcile_generation(db, task, user_id=intruder.id, provider=provider, reason="越权") is None
    assert provider.resume_calls == []


class _MissingProvider:
    def resume(self, provider_request_id: str) -> ProviderOperationResult:
        raise RuntimeError("provider 404 not found")


def test_reconcile_provider_lookup_error_stays_unknown(db: OrmSession) -> None:
    task = _task(db)

    result = services.reconcile_generation(
        db, task, user_id=task.run.user_id, provider=_MissingProvider(), reason="provider 404"
    )

    assert result is not None
    assert result.run.status == "unknown"
    assert result.run.reconciliation_required is True
    assert result.run.error_code == "provider_lookup_unknown"
    assert db.scalar(select(func.count(m.ImageVersion.id)).where(m.ImageVersion.run_id == task.run.id)) == 0
