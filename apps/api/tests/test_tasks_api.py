import os
import time
from collections.abc import Generator

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from tevion_api import models as m
from tevion_api.auth import DEFAULT_AUDIENCE
from tevion_api.db import Base, get_db
from tevion_api.main import app

TEST_DB_URL = os.environ.get(
    "TEVION_TEST_DB_URL",
    "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test",
)
TEST_SECRET = "task-test-secret-0123456789abcdef"
client = TestClient(app)


def _pg_reachable() -> bool:
    try:
        engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect():
            return True
    except Exception:
        return False


def _token(sub: str) -> str:
    payload = {
        "sub": sub,
        "iss": "tevion-local",
        "aud": DEFAULT_AUDIENCE,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, TEST_SECRET, algorithm="HS256")


def _auth(sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(sub)}"}


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEVION_AUTH_DEV_SECRET", TEST_SECRET)
    monkeypatch.setenv("TEVION_OIDC_JWKS_URL", "")


@pytest.fixture(scope="module")
def db_override() -> Generator[None, None, None]:
    if not _pg_reachable():
        pytest.skip("PostgreSQL unavailable: run `docker compose up -d db` first")
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


def _create(db: OrmSession, *, subject: str, request_text: str = "清爽成年男性", mode: str = "explore") -> tuple[str, str]:
    user = m.User(auth_provider="oidc", provider_subject=subject)
    db.add(user)
    db.flush()
    project = m.Project(user_id=user.id, name="默认项目")
    db.add(project)
    db.flush()
    session = m.Session(project_id=project.id, mode=mode, raw_request=request_text, status="created")
    db.add(session)
    db.flush()
    run = m.GenerationRun(session_id=session.id, strategy_version="default", status="created")
    db.add(run)
    db.commit()
    return user.id, session.id


def test_create_task_persists_session_and_run(db_override: None) -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"request": "我想要清爽、少年感但成年的男性肖像", "mode": "explore", "output_count": 4, "aspect_ratio": "4:5"},
        headers=_auth("sub_creator"),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"].startswith("session_")
    assert body["user_id"].startswith("user_")
    assert body["status"] == "created"
    assert body["output_count"] == 4

    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        stored_session = session.get(m.Session, body["task_id"])
        assert stored_session is not None
        assert stored_session.mode == "explore"
        assert stored_session.status == "created"
        run = session.scalar(
            select(m.GenerationRun).where(m.GenerationRun.session_id == body["task_id"])
        )
        assert run is not None
        assert run.strategy_version == "default"
        assert run.parameters_json == {"output_count": 4, "aspect_ratio": "4:5", "quality": "low"}
        # default project was auto-created
        project = session.get(m.Project, stored_session.project_id)
        assert project is not None and project.name == "默认项目"
    engine.dispose()


def test_owner_can_read_task_back(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        _, task_id = _create(session, subject="sub_reader")
    engine.dispose()

    response = client.get(f"/api/v1/tasks/{task_id}", headers=_auth("sub_reader"))

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["request"] == "清爽成年男性"
    assert body["mode"] == "explore"
    assert body["run_id"].startswith("run_")
    assert body["strategy_version"] == "default"


def test_other_user_cannot_read_task(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        _, task_id = _create(session, subject="sub_owner")
    engine.dispose()

    response = client.get(f"/api/v1/tasks/{task_id}", headers=_auth("sub_intruder"))

    assert response.status_code == 404


def test_task_requires_auth(db_override: None) -> None:
    assert client.post("/api/v1/tasks", json={"request": "x", "mode": "explore"}).status_code == 401
    assert client.get("/api/v1/tasks/session_unknown").status_code == 401
