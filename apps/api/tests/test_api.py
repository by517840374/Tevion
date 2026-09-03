from fastapi.testclient import TestClient

from tevion_api.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "tevion-api"


def test_product_metadata_exposes_initial_goal() -> None:
    response = client.get("/api/v1/product")
    assert response.status_code == 200
    assert "adult male" in response.json()["initial_goal"]


def test_create_task_contract() -> None:
    response = client.post(
        "/api/v1/tasks",
        json={"request": "清爽、明确成年的男性人像，光影自然", "mode": "explore"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "created"
    assert body["output_count"] == 4
    assert body["aspect_ratio"] == "4:5"
