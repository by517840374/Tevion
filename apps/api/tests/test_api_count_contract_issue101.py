from tevion_api.main import _output_contract
from tevion_api.schemas import GenerateResponse, GenerationRunResponse, TaskDetail


def test_output_contract_reports_complete_results() -> None:
    contract = _output_contract({"output_count": 4}, actual_count=4, status="completed")

    assert contract == {
        "requested_output_count": 4,
        "actual_output_count": 4,
        "output_completeness": "complete",
        "output_shortfall": 0,
        "retryable": False,
    }


def test_output_contract_reports_partial_results_without_marking_retryable() -> None:
    contract = _output_contract({"output_count": 4}, actual_count=1, status="completed")

    assert contract == {
        "requested_output_count": 4,
        "actual_output_count": 1,
        "output_completeness": "partial",
        "output_shortfall": 3,
        "retryable": False,
    }


def test_output_contract_reports_empty_results_and_retryable_status() -> None:
    contract = _output_contract({"output_count": 4}, actual_count=0, status="unknown")

    assert contract == {
        "requested_output_count": 4,
        "actual_output_count": 0,
        "output_completeness": "empty",
        "output_shortfall": 4,
        "retryable": True,
    }


def test_response_models_expose_count_contract_fields() -> None:
    fields = {
        "requested_output_count",
        "actual_output_count",
        "output_completeness",
        "output_shortfall",
        "retryable",
    }

    assert fields <= set(GenerateResponse.model_fields)
    assert fields <= set(GenerationRunResponse.model_fields)
    assert fields <= set(TaskDetail.model_fields)

    response = GenerateResponse(
        task_id="task-101",
        run_id="run-101",
        status="completed",
        requested_output_count=4,
        actual_output_count=1,
        output_completeness="partial",
        output_shortfall=3,
        retryable=False,
    )
    assert response.output_completeness == "partial"
