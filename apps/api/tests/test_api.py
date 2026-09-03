from fastapi.testclient import TestClient

from tevion_api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_product_metadata() -> None:
    response = client.get("/api/v1/product")
    assert response.status_code == 200
    assert response.json()["initial_goal"]


def test_create_task_preserves_contract() -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"request": "清爽、明确成年的男性肖像", "mode": "explore", "output_count": 4},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "created"


def test_task_runtime_endpoint_exposes_bounded_snapshot() -> None:
    response = client.get("/api/v1/tasks/task_1/runtime")
    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task_1",
        "state": "created",
        "retry_count": 0,
        "max_retries": 2,
        "correlation_id": "task_1",
        "event_count": 0,
    }
