from tevion_api.schemas import CreateTaskRequest


def test_create_task_request_accepts_single_output() -> None:
    request = CreateTaskRequest(request="清爽成年男性", output_count=1)

    assert request.output_count == 1
