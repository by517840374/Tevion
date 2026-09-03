from fastapi import FastAPI

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
    # Task persistence and agent execution are deliberately introduced in later slices.
    # The contract exists now so the frontend can be designed against the product boundary.
    return TaskSummary(
        task_id="task_demo_contract",
        status=TaskStatus.CREATED,
        request=payload.request,
        mode=payload.mode,
        output_count=payload.output_count,
        aspect_ratio=payload.aspect_ratio,
    )
