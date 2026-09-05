from fastapi.testclient import TestClient

from tevion_api.main import app

client = TestClient(app)


def test_reconciliation_command_is_protected() -> None:
    response = client.post(
        "/api/v1/tasks/task-82/generations/run-82/reconcile",
        json={"reason": "人工确认"},
    )

    assert response.status_code == 401


def test_reconciliation_command_requires_a_reason() -> None:
    response = client.post(
        "/api/v1/tasks/task-82/generations/run-82/reconcile",
        json={},
    )

    assert response.status_code == 401


def test_reconciliation_route_is_registered_with_generation_response() -> None:
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", "") == "/api/v1/tasks/{task_id}/generations/{run_id}/reconcile"
    )

    assert route.methods == {"POST"}
    assert route.response_model.__name__ == "GenerationRunResponse"
