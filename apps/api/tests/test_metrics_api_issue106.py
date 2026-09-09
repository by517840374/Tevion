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
TEST_SECRET = "issue-106-test-secret-012345678901"
client = TestClient(app)


def _auth(subject: str) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {"sub": subject, "iss": "tevion-local", "aud": DEFAULT_AUDIENCE, "exp": now + 3600, "iat": now},
        TEST_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


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


def test_metrics_empty_data_returns_zeroed_user_scoped_snapshot(db_override: None) -> None:
    response = client.get("/api/v1/metrics", headers=_auth("issue106-empty"))

    assert response.status_code == 200
    assert response.json() == {
        "generation_completion_rate": 0.0,
        "candidate_selection_rate": 0.0,
        "feedback_completion_rate": 0.0,
        "explore_to_refine_rate": 0.0,
        "average_generation_rounds": 0.0,
        "latency_ms": {
            "count": 0,
            "average": 0.0,
            "total": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        },
        "cost": {"count": 0, "average": 0.0, "total": 0.0},
        "sample_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "unknown_count": 0,
        "unavailable_metrics": ["throughput", "concurrency", "retry_count", "time_to_accept"],
    }


def _seed_metrics_data(db: OrmSession, subject: str) -> None:
    user = m.User(auth_provider="oidc", provider_subject=subject)
    project = m.Project(user=user, name="Metrics")
    explore = m.Session(project=project, mode="explore", status="awaiting_selection")
    explore_run = m.GenerationRun(
        session=explore, user_id=user.id, status="completed", latency_ms=100, estimated_cost=0.2
    )
    explore_image = m.ImageVersion(run=explore_run, asset_uri="s3://explore")
    db.add_all([user, project, explore, explore_run, explore_image])
    db.flush()
    refine = m.Session(project=project, mode="refine", status="awaiting_selection")
    refine_run = m.GenerationRun(
        session=refine, user_id=user.id, parent_run_id=explore_run.id, status="failed", latency_ms=50
    )
    db.add_all(
        [
            user,
            project,
            explore,
            explore_run,
            explore_image,
            refine,
            refine_run,
            m.FeedbackEvent(
                user=user,
                session=explore,
                image_version=explore_image,
                event_type="selected",
                payload_json={"selected": True},
            ),
        ]
    )
    db.flush()


def test_metrics_are_partial_and_isolated_to_current_user(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        _seed_metrics_data(db, "issue106-owner")
        _seed_metrics_data(db, "issue106-other")
        db.commit()
    engine.dispose()

    response = client.get("/api/v1/metrics", headers=_auth("issue106-owner"))
    assert response.status_code == 200
    assert response.json() == {
        "generation_completion_rate": 0.5,
        "candidate_selection_rate": 1.0,
        "feedback_completion_rate": 1.0,
        "explore_to_refine_rate": 1.0,
        "average_generation_rounds": 1.0,
        "latency_ms": {
            "count": 2,
            "average": 75.0,
            "total": 150.0,
            "p50": 75.0,
            "p95": 97.5,
            "p99": 99.5,
        },
        "cost": {"count": 1, "average": 0.2, "total": 0.2},
        "sample_count": 2,
        "completed_count": 1,
        "failed_count": 1,
        "unknown_count": 0,
        "unavailable_metrics": ["throughput", "concurrency", "retry_count", "time_to_accept"],
    }

    other = client.get("/api/v1/metrics", headers=_auth("issue106-unknown"))
    assert other.status_code == 200
    assert other.json()["generation_completion_rate"] == 0.0
    assert other.json()["latency_ms"]["count"] == 0


def test_metrics_percentiles_ignore_missing_latency_and_count_unknown(db_override: None) -> None:
    engine = create_engine(TEST_DB_URL)
    with OrmSession(engine) as db:
        user = m.User(auth_provider="oidc", provider_subject="issue112-percentiles")
        project = m.Project(user=user, name="Metrics")
        session = m.Session(project=project, mode="explore")
        db.add_all(
            [
                user,
                project,
                session,
                m.GenerationRun(session=session, user_id=user.id, status="completed", latency_ms=10),
                m.GenerationRun(session=session, user_id=user.id, status="failed", latency_ms=None),
                m.GenerationRun(session=session, user_id=user.id, status="unknown", latency_ms=30),
            ]
        )
        db.commit()
    engine.dispose()

    response = client.get("/api/v1/metrics", headers=_auth("issue112-percentiles"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["sample_count"] == 3
    assert payload["completed_count"] == 1
    assert payload["failed_count"] == 1
    assert payload["unknown_count"] == 1
    assert payload["latency_ms"]["count"] == 2
    assert payload["latency_ms"]["p50"] == 20.0
    assert payload["latency_ms"]["p95"] == 29.0
    assert payload["latency_ms"]["p99"] == 29.8
