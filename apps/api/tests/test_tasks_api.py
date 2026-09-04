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


def _create(db: OrmSession, *, subject: str, request_text: str = "清爽成年男性", mode: str = "explore") -> tuple[str, str, str, str]:
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
    db.flush()
    image = m.ImageVersion(run_id=run.id, asset_uri="s3://tevion/image-1.png", width=1024, height=1280)
    db.add(image)
    db.commit()
    return user.id, project.id, session.id, image.id


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
        project = session.get(m.Project, stored_session.project_id)
        assert project is not None and project.name == "默认项目"
    engine.dispose()


def test_owner_can_read_task_back(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        _, _, task_id, _ = _create(session, subject="sub_reader")
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
        _, _, task_id, _ = _create(session, subject="sub_owner")
    engine.dispose()

    response = client.get(f"/api/v1/tasks/{task_id}", headers=_auth("sub_intruder"))

    assert response.status_code == 404


def test_owner_can_write_feedback_and_read_project_preferences(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        _, _, task_id, image_id = _create(session, subject="sub_feedback_owner")
    engine.dispose()

    feedback_response = client.post(
        f"/api/v1/tasks/{task_id}/feedback",
        json={
            "version_id": image_id,
            "selected": True,
            "continue_direction": "保留光线，继续这个方向",
        },
        headers=_auth("sub_feedback_owner"),
    )
    assert feedback_response.status_code == 201
    feedback_body = feedback_response.json()
    assert feedback_body["event_type"] == "selected"

    preferences_response = client.get(
        "/api/v1/preferences",
        params={"scope": "project", "task_id": task_id},
        headers=_auth("sub_feedback_owner"),
    )
    assert preferences_response.status_code == 200
    items = preferences_response.json()["items"]
    assert any(item["key"] == "image_version_id" for item in items)
    selected_item = next(item for item in items if item["key"] == "image_version_id")
    assert selected_item["value"] == image_id
    assert selected_item["source"] == "selection"
    assert selected_item["scope"] == "project"
    assert selected_item["confidence"] == 0.7
    assert selected_item["evidence_count"] == 1

    session_preferences = client.get(
        "/api/v1/preferences",
        params={"scope": "session", "task_id": task_id},
        headers=_auth("sub_feedback_owner"),
    )
    assert session_preferences.status_code == 200
    session_items = session_preferences.json()["items"]
    assert any(item["key"] == "direction" for item in session_items)

    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        events = session.scalars(select(m.FeedbackEvent).where(m.FeedbackEvent.session_id == task_id)).all()
        assert len(events) == 1
        assert events[0].image_version_id == image_id
        assert events[0].payload_json["direction"] == "保留光线，继续这个方向"
        reconstructed = [
            (event.event_type, event.image_version_id, event.payload_json.get("direction"), event.payload_json.get("selected"))
            for event in events
        ]
        assert reconstructed == [("selected", image_id, "保留光线，继续这个方向", True)]
    engine.dispose()


def test_other_user_cannot_write_or_read_feedback_preferences(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        _, _, task_id, image_id = _create(session, subject="sub_owner_feedback")
    engine.dispose()

    feedback_response = client.post(
        f"/api/v1/tasks/{task_id}/feedback",
        json={
            "version_id": image_id,
            "rejected": True,
            "rejection_reason": "不是我要的风格",
        },
        headers=_auth("sub_intruder_feedback"),
    )
    assert feedback_response.status_code == 404

    preferences_response = client.get(
        "/api/v1/preferences",
        params={"scope": "project", "task_id": task_id},
        headers=_auth("sub_intruder_feedback"),
    )
    assert preferences_response.status_code == 404


def test_feedback_reject_requires_reason(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        _, _, task_id, image_id = _create(session, subject="sub_reject_reason")
    engine.dispose()

    response = client.post(
        f"/api/v1/tasks/{task_id}/feedback",
        json={"version_id": image_id, "rejected": True},
        headers=_auth("sub_reject_reason"),
    )
    assert response.status_code == 422


def test_task_requires_auth(db_override: None) -> None:
    assert client.post("/api/v1/tasks", json={"request": "x", "mode": "explore"}).status_code == 401
    assert client.get("/api/v1/tasks/session_unknown").status_code == 401
    assert client.post(
        "/api/v1/tasks/session_unknown/feedback",
        json={"version_id": "image_unknown", "selected": True},
    ).status_code == 401
    assert client.get("/api/v1/preferences", params={"scope": "project", "task_id": "session_unknown"}).status_code == 401


def test_refine_task_preserves_parent_lineage(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        _, _, parent_task_id, parent_image_id = _create(session, subject="sub_refine")
        parent_run = session.scalar(select(m.GenerationRun).where(m.GenerationRun.session_id == parent_task_id))
        assert parent_run is not None
    engine.dispose()

    response = client.post(
        "/api/v1/tasks",
        json={
            "request": "保留脸部和光线，简化背景",
            "mode": "refine",
            "parent_version_id": parent_image_id,
            "output_count": 2,
            "aspect_ratio": "4:5",
        },
        headers=_auth("sub_refine"),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["mode"] == "refine"
    assert body["parent_image_id"] == parent_image_id
    assert body["parent_run_id"] == parent_run.id

    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        child_run = session.scalar(select(m.GenerationRun).where(m.GenerationRun.session_id == body["task_id"]))
        assert child_run is not None
        assert child_run.parent_run_id == parent_run.id
        assert child_run.parameters_json["parent_image_id"] == parent_image_id
    engine.dispose()


def test_refine_task_requires_existing_parent(db_override: None) -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"request": "精修", "mode": "refine", "parent_version_id": "image_missing"},
        headers=_auth("sub_refine_missing"),
    )
    assert response.status_code == 422
