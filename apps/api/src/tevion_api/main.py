from fastapi import Depends, FastAPI, HTTPException

from . import services
from .auth import get_current_user
from .db import get_db
from .models import User
from .schemas import (
    CreateTaskRequest,
    HealthResponse,
    ProductMetadata,
    TaskDetail,
    TaskStatus,
    TaskSummary,
)
from sqlalchemy.orm import Session as OrmSession

app = FastAPI(title="Tevion Product API", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/v1/product", response_model=ProductMetadata)
def product_metadata() -> ProductMetadata:
    return ProductMetadata()


@app.post("/api/v1/tasks", response_model=TaskSummary, status_code=202)
def create_task(
    payload: CreateTaskRequest,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> TaskSummary:
    created = services.create_task(
        db,
        current_user,
        request=payload.request,
        mode=payload.mode,
        parameters={"output_count": payload.output_count, "aspect_ratio": payload.aspect_ratio},
    )
    return TaskSummary(
        task_id=created.session.id,
        user_id=current_user.id,
        status=TaskStatus(created.session.status),
        request=created.session.raw_request or "",
        mode=created.session.mode,
        output_count=payload.output_count,
        aspect_ratio=payload.aspect_ratio,
    )


@app.get("/api/v1/tasks/{task_id}", response_model=TaskDetail)
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
) -> TaskDetail:
    task = services.get_task_for_user(db, current_user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    params = task.run.parameters_json or {}
    return TaskDetail(
        task_id=task.session.id,
        status=TaskStatus(task.session.status),
        mode=task.session.mode,
        request=task.session.raw_request or "",
        run_id=task.run.id,
        strategy_version=task.run.strategy_version,
        output_count=params.get("output_count"),
        aspect_ratio=params.get("aspect_ratio"),
        created_at=task.session.created_at,
    )


@app.get("/api/v1/tasks/{task_id}/runtime")
def task_runtime(task_id: str) -> dict[str, object]:
    """Expose the bounded runtime shape while persistence is not yet wired."""
    from .runtime import TaskRuntime

    runtime = TaskRuntime(task_id)
    return runtime.snapshot()


__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
