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


def test_create_task_requires_authentication() -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"request": "清爽、明确成年的男性肖像", "mode": "explore", "output_count": 4},
    )
    assert response.status_code == 401


def test_task_runtime_endpoint_requires_authentication() -> None:
    response = client.get("/api/v1/tasks/task_1/runtime")
    assert response.status_code == 401
