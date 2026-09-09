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
TEST_SECRET = "issue-104-test-secret-0123456789"
client = TestClient(app)


def _token(subject: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": subject, "iss": "tevion-local", "aud": DEFAULT_AUDIENCE, "exp": now + 3600, "iat": now},
        TEST_SECRET,
        algorithm="HS256",
    )


def _auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(subject)}"}


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEVION_AUTH_DEV_SECRET", TEST_SECRET)
    monkeypatch.setenv("TEVION_OIDC_JWKS_URL", "")


@pytest.fixture(scope="module")
def db_override() -> Generator[None, None, None]:
    try:
        engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except Exception:
        pytest.skip("PostgreSQL unavailable")
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


def _create_task(db: OrmSession, subject: str) -> tuple[str, str]:
    user = m.User(auth_provider="oidc", provider_subject=subject)
    project = m.Project(user=user, name="Preference project")
    session = m.Session(project=project, mode="explore", raw_request="portrait", status="created")
    run = m.GenerationRun(session=session, strategy_version="default", status="created")
    db.add_all([user, project, session, run])
    db.commit()
    return session.id, project.id


def test_owner_can_create_read_and_edit_preference_with_stable_identity_and_lineage(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        task_id, project_id = _create_task(db, "issue104-owner")
    engine.dispose()

    created = client.post(
        "/api/v1/preferences",
        json={"scope": "project", "scope_id": project_id, "task_id": task_id, "key": "lighting", "value": "soft"},
        headers=_auth("issue104-owner"),
    )
    assert created.status_code == 201
    body = created.json()
    preference_id = body["id"]
    assert body["status"] == "active"
    assert body["evidence_ids"]

    read = client.get(
        "/api/v1/preferences", params={"scope": "project", "task_id": task_id}, headers=_auth("issue104-owner")
    )
    item = next(item for item in read.json()["items"] if item["key"] == "lighting")
    assert item["id"] == preference_id
    assert item["value"] == "soft"
    assert item["status"] == "active"
    assert item["evidence_ids"] == body["evidence_ids"]

    edited = client.patch(
        f"/api/v1/preferences/{preference_id}",
        json={"value": "hard"},
        headers=_auth("issue104-owner"),
    )
    assert edited.status_code == 200
    assert edited.json()["id"] == preference_id
    assert edited.json()["value"] == "hard"
    assert edited.json()["status"] == "active"
    assert len(edited.json()["evidence_ids"]) == 2

    disabled = client.post(
        f"/api/v1/preferences/{preference_id}/disable",
        headers=_auth("issue104-owner"),
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert len(disabled.json()["evidence_ids"]) == 3


def test_intruder_cannot_read_or_mutate_preference(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        task_id, project_id = _create_task(db, "issue104-owner-boundary")
    engine.dispose()
    created = client.post(
        "/api/v1/preferences",
        json={"scope": "project", "scope_id": project_id, "task_id": task_id, "key": "color", "value": "blue"},
        headers=_auth("issue104-owner-boundary"),
    )
    preference_id = created.json()["id"]

    assert (
        client.get(
            "/api/v1/preferences", params={"scope": "project", "task_id": task_id}, headers=_auth("issue104-intruder")
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/preferences/{preference_id}", json={"value": "red"}, headers=_auth("issue104-intruder")
        ).status_code
        == 404
    )


def test_disable_delete_and_repeated_mutation_are_idempotent(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        task_id, project_id = _create_task(db, "issue104-status")
    engine.dispose()
    created = client.post(
        "/api/v1/preferences",
        json={"scope": "project", "scope_id": project_id, "task_id": task_id, "key": "contrast", "value": "high"},
        headers=_auth("issue104-status"),
    )
    preference_id = created.json()["id"]
    url = f"/api/v1/preferences/{preference_id}"

    disabled = client.post(f"{url}/disable", headers=_auth("issue104-status"))
    assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"
    repeated = client.post(f"{url}/disable", headers=_auth("issue104-status"))
    assert repeated.status_code == 200 and repeated.json()["status"] == "disabled"
    assert (
        client.get(
            "/api/v1/preferences", params={"scope": "project", "task_id": task_id}, headers=_auth("issue104-status")
        ).json()["items"]
        == []
    )

    deleted = client.delete(url, headers=_auth("issue104-status"))
    assert deleted.status_code == 200 and deleted.json()["status"] == "deleted"
    repeated_delete = client.delete(url, headers=_auth("issue104-status"))
    assert repeated_delete.status_code == 200 and repeated_delete.json()["status"] == "deleted"

    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        events = db.scalars(select(m.PreferenceEvent).where(m.PreferenceEvent.preference_id == preference_id)).all()
        assert len(events) == 3
        assert [event.deleted for event in events] == [False, False, True]
    engine.dispose()


def test_scope_id_must_be_owned_and_user_scope_is_supported(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        task_id, project_id = _create_task(db, "issue104-scope")
    engine.dispose()
    response = client.post(
        "/api/v1/preferences",
        json={"scope": "session", "scope_id": project_id, "task_id": task_id, "key": "x", "value": "y"},
        headers=_auth("issue104-scope"),
    )
    assert response.status_code == 422
    user_pref = client.post(
        "/api/v1/preferences",
        json={"scope": "user", "task_id": task_id, "key": "palette", "value": "warm"},
        headers=_auth("issue104-scope"),
    )
    assert user_pref.status_code == 201
    assert user_pref.json()["scope_id"] is None
    assert user_pref.json()["status"] == "active"


def test_existing_preference_read_contract_remains_compatible(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        task_id, project_id = _create_task(db, "issue104-compat")
        db.add(
            m.PreferenceEvent(
                user_id=db.scalar(select(m.User.id).where(m.User.provider_subject == "issue104-compat")),
                scope="project",
                scope_id=project_id,
                key="legacy",
                value="yes",
                source="selection",
            )
        )
        db.commit()
    engine.dispose()
    response = client.get(
        "/api/v1/preferences", params={"scope": "project", "task_id": task_id}, headers=_auth("issue104-compat")
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["key"] == "legacy"
    assert response.json()["items"][0]["confidence"] == 0.7
