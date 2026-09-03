from fastapi import FastAPI

from .runtime import TaskRuntime, TaskState
from .schemas import CreateTaskRequest, HealthResponse, ProductMetadata, TaskStatus, TaskSummary

app = FastAPI(title="Tevion Product API", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/v1/product", response_model=ProductMetadata)
def product_metadata() -> ProductMetadata:
    return ProductMetadata()


@app.post("/api/v1/tasks", response_model=TaskSummary, status_code=202)
def create_task(payload: CreateTaskRequest) -> TaskSummary:
    # Runtime persistence and provider execution are introduced in later slices.
    runtime = TaskRuntime("task_demo_contract")
    runtime.transition(TaskState.UNDERSTANDING, event_type="task_created")
    return TaskSummary(
        task_id=runtime.task_id,
        status=TaskStatus.CREATED,
        request=payload.request,
        mode=payload.mode,
        output_count=payload.output_count,
        aspect_ratio=payload.aspect_ratio,
    )


@app.get("/api/v1/tasks/{task_id}/runtime")
def task_runtime(task_id: str) -> dict[str, object]:
    """Expose the bounded runtime shape while persistence is not yet wired."""
    runtime = TaskRuntime(task_id)
    return runtime.snapshot()


__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
