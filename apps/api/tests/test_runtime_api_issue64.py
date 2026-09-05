import os
import time
from collections.abc import Generator

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from tevion_api import models as m
from tevion_api.auth import DEFAULT_AUDIENCE
from tevion_api.db import Base, get_db
from tevion_api.main import app

TEST_DB_URL = os.environ.get("TEVION_TEST_DB_URL", "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test")
TEST_SECRET = "issue-64-test-secret-012345678901"
client = TestClient(app)


def _token(sub: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "iss": "tevion-local", "aud": DEFAULT_AUDIENCE, "exp": now + 3600, "iat": now},
        TEST_SECRET,
        algorithm="HS256",
    )


def _auth(sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(sub)}"}


def _reachable() -> bool:
    try:
        engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect():
            return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEVION_AUTH_DEV_SECRET", TEST_SECRET)
    monkeypatch.setenv("TEVION_OIDC_JWKS_URL", "")


@pytest.fixture(scope="module")
def db_override() -> Generator[None, None, None]:
    if not _reachable():
        pytest.skip("PostgreSQL unavailable")
    engine = create_engine(TEST_DB_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    def override() -> Generator[OrmSession, None, None]:
        with OrmSession(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _create_task(subject: str, *, session_status: str = "created", run_status: str = "created") -> str:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        user = m.User(auth_provider="oidc", provider_subject=subject)
        db.add(user)
        db.flush()
        project = m.Project(user_id=user.id, name="Issue 64")
        db.add(project)
        db.flush()
        session = m.Session(project_id=project.id, status=session_status, mode="explore")
        db.add(session)
        db.flush()
        db.add(m.GenerationRun(session_id=session.id, strategy_version="default", status=run_status))
        db.commit()
        task_id = session.id
    engine.dispose()
    return task_id


def test_runtime_requires_authentication(db_override: None) -> None:
    response = client.get("/api/v1/tasks/does-not-matter/runtime")
    assert response.status_code == 401


def test_runtime_is_owned_and_projects_persisted_status(db_override: None) -> None:
    task_id = _create_task("issue64-owner", session_status="awaiting_selection", run_status="completed")
    assert client.get(f"/api/v1/tasks/{task_id}/runtime", headers=_auth("issue64-intruder")).status_code == 404
    response = client.get(f"/api/v1/tasks/{task_id}/runtime", headers=_auth("issue64-owner"))
    assert response.status_code == 200
    assert response.json()["state"] == "awaiting_selection"
    assert response.json()["session_status"] == "awaiting_selection"
    assert response.json()["generation_status"] == "completed"


def test_runtime_refresh_reads_updated_db_status(db_override: None) -> None:
    task_id = _create_task("issue64-refresh")
    assert client.get(f"/api/v1/tasks/{task_id}/runtime", headers=_auth("issue64-refresh")).status_code == 200
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        task = db.get(m.Session, task_id)
        assert task is not None
        task.status = "awaiting_selection"
        task.runs[0].status = "completed"
        db.commit()
    engine.dispose()
    response = client.get(f"/api/v1/tasks/{task_id}/runtime", headers=_auth("issue64-refresh"))
    assert response.json()["state"] == "awaiting_selection"
    assert response.json()["event_count"] == 0


def test_runtime_projects_failed_run_as_needs_user_review(db_override: None) -> None:
    task_id = _create_task("issue64-failed", run_status="failed")
    response = client.get(f"/api/v1/tasks/{task_id}/runtime", headers=_auth("issue64-failed"))
    assert response.status_code == 200
    assert response.json()["state"] == "needs_user_review"
    assert response.json()["generation_status"] == "failed"


def test_missing_runtime_task_is_not_disclosed(db_override: None) -> None:
    assert client.get("/api/v1/tasks/missing/runtime", headers=_auth("issue64-owner")).status_code == 404
