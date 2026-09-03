import os
import time
from collections.abc import Generator

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tevion_api import models as m
from tevion_api.auth import AUTH_PROVIDER, DEFAULT_AUDIENCE
from tevion_api.db import Base, get_db
from tevion_api.main import app

TEST_DB_URL = os.environ.get(
    "TEVION_TEST_DB_URL",
    "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test",
)

TEST_SECRET = "test-secret-please-change-0123456789abcdef"
client = TestClient(app)


def _pg_reachable() -> bool:
    try:
        engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect():
            return True
    except Exception:
        return False


def _token(
    *,
    sub: str = "sub_test",
    secret: str = TEST_SECRET,
    exp_offset: int = 3600,
    issuer: str = "tevion-local",
    audience: str = DEFAULT_AUDIENCE,
    **claims: object,
) -> str:
    payload: dict[str, object] = {
        "sub": sub,
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    payload.update(claims)
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEVION_AUTH_DEV_SECRET", TEST_SECRET)
    monkeypatch.setenv("TEVION_OIDC_JWKS_URL", "")
    monkeypatch.delenv("TEVION_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("TEVION_AUTH_AUDIENCE", raising=False)


def test_create_task_without_token_is_rejected() -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"request": "清爽成年男性", "mode": "explore", "output_count": 2},
    )
    assert response.status_code == 401


def test_create_task_with_garbage_token_is_rejected() -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"request": "清爽成年男性", "mode": "explore", "output_count": 2},
        headers={"Authorization": "Bearer not.a.jwt"},
    )
    assert response.status_code == 401


def test_create_task_with_wrong_signature_is_rejected() -> None:
    forged = _token(secret="attacker-secret-0123456789abcdef")
    response = client.post(
        "/api/v1/tasks",
        json={"request": "清爽成年男性", "mode": "explore", "output_count": 2},
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert response.status_code == 401


def test_create_task_with_expired_token_is_rejected() -> None:
    stale = _token(exp_offset=-60)
    response = client.post(
        "/api/v1/tasks",
        json={"request": "清爽成年男性", "mode": "explore", "output_count": 2},
        headers={"Authorization": f"Bearer {stale}"},
    )
    assert response.status_code == 401


def test_health_and_product_metadata_remain_public() -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/product").status_code == 200


@pytest.fixture(scope="module")
def db_override() -> Generator[None, None, None]:
    if not _pg_reachable():
        pytest.skip("PostgreSQL unavailable: run `docker compose up -d db` first")
    engine = create_engine(TEST_DB_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    def override() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_valid_token_maps_to_local_user_and_creates_task(db_override: None) -> None:
    subject = "sub_from_oidc_provider"
    token = _token(sub=subject, email="user@example.com")

    response = client.post(
        "/api/v1/tasks",
        json={"request": "清爽成年男性", "mode": "explore", "output_count": 2},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "created"
    assert body["user_id"].startswith("user_")

    engine = create_engine(TEST_DB_URL)
    with Session(engine) as session:
        stored = session.scalar(
            select(m.User).where(
                m.User.auth_provider == AUTH_PROVIDER,
                m.User.provider_subject == subject,
            )
        )
        assert stored is not None
        assert stored.email == "user@example.com"
        assert stored.id == body["user_id"]
    engine.dispose()


def test_repeated_valid_token_reuses_same_user(db_override: None) -> None:
    token = _token(sub="sub_returning")

    first = client.post(
        "/api/v1/tasks",
        json={"request": "a", "mode": "refine", "output_count": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    second = client.post(
        "/api/v1/tasks",
        json={"request": "b", "mode": "explore", "output_count": 2},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["user_id"] == second.json()["user_id"]
