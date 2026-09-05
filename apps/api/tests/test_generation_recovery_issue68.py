import os
import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session as OrmSession

from tevion_api import models as m
from tevion_api import services
from tevion_api.db import Base
from tevion_api.provider import GenerationRequest, GenerationResult, ProviderResponseError

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


class SuccessProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        return GenerationResult(
            provider_name="fake",
            provider_request_id="provider-run-1",
            model_name="gpt-image-2",
            asset_urls=["https://cdn.example.test/one.png"],
            latency_ms=7,
            metadata_source="fake",
            cost=0.01,
        )


class FailingProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise self.error


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
    user = m.User(auth_provider="oidc", provider_subject=f"issue68-{uuid.uuid4().hex}")
    db.add(user)
    db.flush()
    return services.create_task(db, user, request="portrait", mode="explore", parameters={"output_count": 1})


def test_provider_timeout_is_recoverable_unknown_not_failed(db: OrmSession) -> None:
    task = _task(db)

    with pytest.raises(ProviderResponseError):
        services.execute_generation(db, task, FailingProvider(ProviderResponseError("provider task timed out")))

    db.expire_all()
    run = db.get(m.GenerationRun, task.run.id)
    assert run is not None
    assert run.status == "unknown"
    assert run.error_code == "provider_timeout_unknown"
    assert run.error_message == "provider request outcome is unknown; recovery required"


def test_completed_finalize_is_idempotent_per_run(db: OrmSession) -> None:
    task = _task(db)
    provider = SuccessProvider()

    first = services.execute_generation(db, task, provider)
    second = services.execute_generation(db, task, provider)

    assert provider.calls == 1
    assert [image.id for image in second] == [image.id for image in first]
    assert db.scalar(select(func.count(m.ImageVersion.id)).where(m.ImageVersion.run_id == task.run.id)) == 1
    run = db.get(m.GenerationRun, task.run.id)
    assert run is not None
    assert run.provider_request_id == "provider-run-1"
    assert run.estimated_cost == 0.01


def test_generating_run_runtime_is_recovery_state_without_provider_submit(db: OrmSession) -> None:
    task = _task(db)
    task.run.status = "generating"
    task.session.status = "generating"
    db.commit()

    projection = services.get_runtime_projection_for_user(db, task.run.user_id, task.session.id)

    assert projection is not None
    assert projection.state == "recovery_required"
    assert projection.generation_status == "generating"
