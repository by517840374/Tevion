from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class TaskState(StrEnum):
    CREATED = "created"
    UNDERSTANDING = "understanding"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    PLANNING = "planning"
    EXPLORING = "exploring"
    REFINING = "refining"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    RETRYING = "retrying"
    AWAITING_SELECTION = "awaiting_selection"
    NEEDS_USER_REVIEW = "needs_user_review"
    COMPLETED = "completed"


class InvalidTransition(ValueError):
    pass


@dataclass(frozen=True)
class TaskEvent:
    event_id: str
    task_id: str
    event_type: str
    from_state: TaskState | None
    to_state: TaskState
    correlation_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_ALLOWED: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({TaskState.UNDERSTANDING}),
    TaskState.UNDERSTANDING: frozenset({TaskState.AWAITING_CONFIRMATION, TaskState.PLANNING}),
    TaskState.AWAITING_CONFIRMATION: frozenset({TaskState.PLANNING, TaskState.NEEDS_USER_REVIEW}),
    TaskState.PLANNING: frozenset({TaskState.EXPLORING, TaskState.REFINING}),
    TaskState.EXPLORING: frozenset({TaskState.GENERATING}),
    TaskState.REFINING: frozenset({TaskState.GENERATING}),
    TaskState.GENERATING: frozenset({TaskState.EVALUATING, TaskState.NEEDS_USER_REVIEW}),
    TaskState.EVALUATING: frozenset({TaskState.AWAITING_SELECTION, TaskState.RETRYING, TaskState.NEEDS_USER_REVIEW}),
    TaskState.RETRYING: frozenset({TaskState.GENERATING, TaskState.NEEDS_USER_REVIEW}),
    TaskState.AWAITING_SELECTION: frozenset({TaskState.COMPLETED, TaskState.REFINING}),
    TaskState.NEEDS_USER_REVIEW: frozenset({TaskState.PLANNING, TaskState.RETRYING, TaskState.COMPLETED}),
    TaskState.COMPLETED: frozenset(),
}


class TaskRuntime:
    def __init__(self, task_id: str, *, max_retries: int = 2, correlation_id: str | None = None) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.task_id = task_id
        self.state = TaskState.CREATED
        self.max_retries = max_retries
        self.retry_count = 0
        self.correlation_id = correlation_id or task_id
        self.events: list[TaskEvent] = []

    def transition(self, to_state: TaskState, *, event_type: str, payload: dict[str, Any] | None = None) -> TaskEvent:
        if to_state not in _ALLOWED[self.state]:
            raise InvalidTransition(f"cannot transition {self.state} -> {to_state}")
        if to_state == TaskState.RETRYING:
            if self.retry_count >= self.max_retries:
                raise InvalidTransition("retry budget exhausted")
            self.retry_count += 1
        event = TaskEvent(
            event_id=f"{self.task_id}:event:{len(self.events) + 1}",
            task_id=self.task_id,
            event_type=event_type,
            from_state=self.state,
            to_state=to_state,
            correlation_id=self.correlation_id,
            payload=payload or {},
        )
        self.events.append(event)
        self.state = to_state
        return event

    def replay(self, events: list[TaskEvent]) -> None:
        self.state = TaskState.CREATED
        self.retry_count = 0
        self.events = []
        for event in events:
            if event.task_id != self.task_id or event.correlation_id != self.correlation_id:
                raise ValueError("event does not belong to this task runtime")
            self.transition(event.to_state, event_type=event.event_type, payload=event.payload)

    def snapshot(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "correlation_id": self.correlation_id,
            "event_count": len(self.events),
        }
