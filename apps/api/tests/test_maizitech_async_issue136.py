import os
import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from tevion_api import models as m
from tevion_api import services
from tevion_api.db import Base
from tevion_api.provider import GenerationRequest, GenerationResult, ProviderOperationResult, ProviderOperationStatus

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


@pytest.fixture()
def db() -> Generator[OrmSession, None, None]:
    engine = create_engine(TEST_DB_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with OrmSession(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _task(db: OrmSession) -> services.CreatedTask:
    user = m.User(auth_provider="oidc", provider_subject=f"issue136-{uuid.uuid4().hex}")
    db.add(user)
    db.flush()
    return services.create_task(db, user, request="portrait", mode="explore", parameters={"output_count": 1})


class PendingProvider:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.poll_calls = 0

    def submit(self, request: GenerationRequest) -> ProviderOperationResult:
        self.submit_calls += 1
        return ProviderOperationResult(ProviderOperationStatus.PENDING, "maizi-task-136")

    def poll(self, provider_request_id: str, *, requested_count: int = 1) -> ProviderOperationResult:
        self.poll_calls += 1
        raise AssertionError("initial submit must not poll synchronously")

    def resume(self, provider_request_id: str, *, requested_count: int = 1) -> ProviderOperationResult:
        return ProviderOperationResult(
            ProviderOperationStatus.COMPLETED,
            provider_request_id,
            result=GenerationResult(
                provider_name="maizitech",
                provider_request_id=provider_request_id,
                model_name="gpt-image-2",
                asset_urls=["data:image/png;base64,YQ=="],
                latency_ms=1,
                metadata_source="provider_response",
                requested_count=requested_count,
            ),
        )

    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise AssertionError("async provider must not use synchronous generate")


def test_pending_submit_is_persisted_and_returns_without_polling(db):
    task = _task(db)
    provider = PendingProvider()

    images = services.execute_generation(db, task, provider)

    assert images == []
    assert task.run.status == "generating"
    assert task.run.provider_request_id == "maizi-task-136"
    assert task.session.status == "generating"
    assert provider.submit_calls == 1


def test_reconcile_pending_run_queries_by_id_and_finalizes_idempotently(db):
    task = _task(db)
    provider = PendingProvider()
    services.execute_generation(db, task, provider)

    first = services.reconcile_generation(
        db, task, user_id=task.run.user_id or "", provider=provider, reason="恢复"
    )
    second = services.reconcile_generation(
        db, task, user_id=task.run.user_id or "", provider=provider, reason="重复恢复"
    )

    assert first is not None
    assert first.run.status == "completed"
    assert second is not None
    assert second.run.status == "completed"
    assert len(first.run.image_versions) == 1
