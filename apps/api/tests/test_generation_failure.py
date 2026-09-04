import os
import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from tevion_api import models as m
from tevion_api import services
from tevion_api.db import Base
from tevion_api.provider import GenerationRequest, ProviderResponseError

TEST_DB_URL = os.environ.get(
    "TEVION_TEST_DB_URL",
    "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test",
)


def _pg_reachable() -> bool:
    try:
        engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(),
    reason="PostgreSQL unavailable: run `docker compose up -d db` first",
)


class FailingProvider:
    """Fake provider that simulates a provider-side failure."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def generate(self, request: GenerationRequest):
        raise self.error


@pytest.fixture(scope="module")
def db() -> Generator[OrmSession, None, None]:
    engine = create_engine(TEST_DB_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with OrmSession(engine) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def _task(db: OrmSession) -> services.CreatedTask:
    user = m.User(auth_provider="oidc", provider_subject=f"sub_failure_test_{uuid.uuid4().hex[:8]}")
    db.add(user)
    db.flush()
    return services.create_task(db, user, request="清爽成年男性", mode="explore", parameters={"output_count": 1})


def test_provider_failure_is_recorded_on_run(db: OrmSession) -> None:
    task = _task(db)
    with pytest.raises(ProviderResponseError):
        services.execute_generation(db, task, FailingProvider(ProviderResponseError("provider task failed: boom")))

    db.expire_all()
    run = db.get(m.GenerationRun, task.run.id)
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "provider_error"
    assert run.error_message == "provider task failed: boom"
    # session must not advance to awaiting_selection on failure
    session = db.get(m.Session, task.session.id)
    assert session is not None
    assert session.status == "created"


def test_unexpected_failure_is_recorded_as_internal(db: OrmSession) -> None:
    task = _task(db)
    with pytest.raises(RuntimeError):
        services.execute_generation(db, task, FailingProvider(RuntimeError("unexpected")))

    db.expire_all()
    run = db.get(m.GenerationRun, task.run.id)
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "internal"
    assert run.error_message == "unexpected"
