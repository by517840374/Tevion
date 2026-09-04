import os
import time
from collections.abc import Generator

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session as OrmSession

from tevion_api import models as m
from tevion_api.auth import DEFAULT_AUDIENCE
from tevion_api.db import Base, get_db
from tevion_api.main import app, get_image_provider
from tevion_api.provider import GenerationRequest, GenerationResult

TEST_DB_URL = os.environ.get(
    "TEVION_TEST_DB_URL",
    "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test",
)
TEST_SECRET = "gen-test-secret-0123456789abcdef"
client = TestClient(app)


class FakeProvider:
    """Zero-cost provider double returning two canned image URLs."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        return GenerationResult(
            provider_request_id="fake_task_1",
            model_name="gpt-image-2",
            asset_urls=[
                "https://cdn.example.test/candidate-1.png",
                "https://cdn.example.test/candidate-2.png",
            ],
            latency_ms=12,
            cost=0.01,
            metadata={"provider": "maizitech", "size": "1:1"},
        )


fake_provider = FakeProvider()


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
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEVION_AUTH_DEV_SECRET", TEST_SECRET)
    monkeypatch.setenv("TEVION_OIDC_JWKS_URL", "")


@pytest.fixture(autouse=True)
def _reset_fake() -> Generator[None, None, None]:
    fake_provider.calls = 0
    yield


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
    app.dependency_overrides[get_image_provider] = lambda: fake_provider
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _create_task(sub: str = "sub_gen") -> str:
    response = client.post(
        "/api/v1/tasks",
        json={"request": "清爽成年男性，柔和侧光", "mode": "explore", "output_count": 2, "aspect_ratio": "1:1"},
        headers=_auth(sub),
    )
    assert response.status_code == 202
    return response.json()["task_id"]


def test_generate_persists_images_and_updates_status(db_override: None) -> None:
    task_id = _create_task()

    response = client.post(f"/api/v1/tasks/{task_id}/generate", headers=_auth("sub_gen"))

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["status"] == "awaiting_selection"
    assert len(body["images"]) == 2
    assert body["images"][0]["url"] == "https://cdn.example.test/candidate-1.png"
    assert body["images"][0]["width"] is None  # "1:1" is a ratio, not pixels

    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        run = session.scalar(select(m.GenerationRun).where(m.GenerationRun.session_id == task_id))
        assert run is not None
        assert run.status == "completed"
        assert run.model_name == "gpt-image-2"
        assert run.estimated_cost == 0.01
        assert run.latency_ms == 12
        count = session.scalar(
            select(func.count(m.ImageVersion.id)).where(m.ImageVersion.run_id == run.id)
        )
        assert count == 2
        stored_session = session.get(m.Session, task_id)
        assert stored_session is not None
        assert stored_session.status == "awaiting_selection"
    engine.dispose()


def test_refine_generation_preserves_parent_image_lineage(db_override: None) -> None:
    parent_task_id = _create_task(sub="sub_refine_generate")
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        parent_run = session.scalar(select(m.GenerationRun).where(m.GenerationRun.session_id == parent_task_id))
        assert parent_run is not None
        parent_run_id = parent_run.id
        parent_image = m.ImageVersion(run_id=parent_run_id, asset_uri="s3://tevion/parent.png")
        session.add(parent_image)
        session.commit()
        parent_image_id = parent_image.id
    engine.dispose()

    response = client.post(
        "/api/v1/tasks",
        json={"request": "保留主体，精修背景", "mode": "refine", "parent_version_id": parent_image_id, "output_count": 2},
        headers=_auth("sub_refine_generate"),
    )
    assert response.status_code == 202
    child_task_id = response.json()["task_id"]
    generated = client.post(f"/api/v1/tasks/{child_task_id}/generate", headers=_auth("sub_refine_generate"))
    assert generated.status_code == 200
    assert all(image["parent_image_id"] == parent_image_id for image in generated.json()["images"])

    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        child_run = session.scalar(select(m.GenerationRun).where(m.GenerationRun.session_id == child_task_id))
        assert child_run is not None
        assert child_run.parent_run_id == parent_run_id
        children = session.scalars(select(m.ImageVersion).where(m.ImageVersion.run_id == child_run.id)).all()
        assert children and all(image.parent_image_id == parent_image_id for image in children)
    engine.dispose()


def test_generate_by_other_user_is_404(db_override: None) -> None:
    task_id = _create_task(sub="sub_owner_gen")

    response = client.post(f"/api/v1/tasks/{task_id}/generate", headers=_auth("sub_intruder_gen"))

    assert response.status_code == 404
    assert fake_provider.calls == 0


def test_task_detail_includes_images_after_generate(db_override: None) -> None:
    task_id = _create_task()
    client.post(f"/api/v1/tasks/{task_id}/generate", headers=_auth("sub_gen"))

    response = client.get(f"/api/v1/tasks/{task_id}", headers=_auth("sub_gen"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_selection"
    assert len(body["images"]) == 2


def test_generate_requires_auth(db_override: None) -> None:
    assert client.post("/api/v1/tasks/session_x/generate").status_code == 401


def test_dev_token_enabled_with_dev_secret(db_override: None) -> None:
    response = client.post("/api/v1/auth/dev-token")
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert token.count(".") == 2  # looks like a JWT
    # and the token actually works
    task = client.post(
        "/api/v1/tasks", json={"request": "x", "mode": "explore"}, headers=_auth("demo_user")
    )
    assert task.status_code == 202


def test_dev_token_disabled_without_dev_secret(
    db_override: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEVION_AUTH_DEV_SECRET")
    response = client.post("/api/v1/auth/dev-token")
    assert response.status_code == 503
