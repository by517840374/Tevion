import os
import time
from collections.abc import Generator

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession

from tevion_api import models as m
from tevion_api.assets import AssetError, LocalAssetStore
from tevion_api.auth import DEFAULT_AUDIENCE
from tevion_api.db import Base, get_db
from tevion_api.main import app

TEST_DB_URL = os.environ.get("TEVION_TEST_DB_URL", "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test")
TEST_SECRET = "reference-upload-test-secret-0123456789"
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


@pytest.fixture
def db(db_override: None) -> Generator[OrmSession, None, None]:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as session:
        yield session
    engine.dispose()


def test_reference_upload_endpoint_requires_authentication() -> None:
    response = client.post(
        "/api/v1/projects/project_1/reference-images",
        files={"file": ("reference.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
    )
    assert response.status_code == 401


def test_reference_image_upload_rejects_content_that_does_not_match_mime(tmp_path) -> None:
    store = LocalAssetStore(tmp_path)
    with pytest.raises(AssetError, match="image"):
        store.persist_upload(b"not an image", "image/png")


def test_reference_image_upload_contract_creates_parent_version(db: OrmSession, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEVION_ASSET_ROOT", str(tmp_path))
    project_response = client.post("/api/v1/projects", json={"name": "上传项目"}, headers=_auth("upload-owner"))
    project_id = project_response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/reference-images",
        files={"file": ("reference.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
        headers=_auth("upload-owner"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("image_")
    assert body["parent_version_id"] == body["id"]
    assert body["url"] == f"/api/v1/assets/{body['asset_key']}"
    assert body["mime_type"] == "image/png"
    stored = db.get(m.ImageVersion, body["id"])
    assert stored is not None
    assert stored.asset_uri.startswith("tevion://assets/")
    assert stored.run.session.project_id == project_id


def test_reference_image_upload_rejects_foreign_project(db: OrmSession) -> None:
    owner_project = client.post("/api/v1/projects", json={"name": "私有项目"}, headers=_auth("upload-owner-a"))
    project_id = owner_project.json()["id"]
    response = client.post(
        f"/api/v1/projects/{project_id}/reference-images",
        files={"file": ("reference.png", b"\x89PNG\r\n\x1a\nimage", "image/png")},
        headers=_auth("upload-owner-b"),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "project not found"


def test_reference_image_upload_rejects_unsupported_and_oversized_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEVION_ASSET_ROOT", str(tmp_path))
    project_response = client.post("/api/v1/projects", json={"name": "校验项目"}, headers=_auth("upload-validation"))
    project_id = project_response.json()["id"]
    unsupported = client.post(
        f"/api/v1/projects/{project_id}/reference-images",
        files={"file": ("notes.txt", b"plain text", "text/plain")},
        headers=_auth("upload-validation"),
    )
    assert unsupported.status_code == 415
    oversized = client.post(
        f"/api/v1/projects/{project_id}/reference-images",
        files={"file": ("large.png", b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024), "image/png")},
        headers=_auth("upload-validation"),
    )
    assert oversized.status_code == 413
