from fastapi.testclient import TestClient

from tevion_api.main import app
from tevion_api.models import GenerationRun

client = TestClient(app)


def test_generation_run_declares_nullable_recovery_columns() -> None:
    columns = GenerationRun.__table__.c
    for name in (
        "phase",
        "last_polled_at",
        "next_poll_at",
        "reconciliation_required",
        "reconciliation_reason",
        "finalized_at",
    ):
        assert name in columns
        assert columns[name].nullable is True


def test_generation_run_query_contract_is_exposed_without_provider_execution() -> None:
    response = client.get("/api/v1/tasks/task_1/generations/run_1")
    assert response.status_code == 401
    response_models = {
        route.response_model.__name__ for route in app.routes if getattr(route, "response_model", None) is not None
    }
    assert "GenerationRunResponse" in response_models
