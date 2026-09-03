import pytest

from tevion_api.runtime import InvalidTransition, TaskRuntime, TaskState


def test_runtime_follows_bounded_explore_path() -> None:
    runtime = TaskRuntime("task_1", max_retries=1)
    for state, event_type in [
        (TaskState.UNDERSTANDING, "understanding_started"),
        (TaskState.PLANNING, "interpretation_confirmed"),
        (TaskState.EXPLORING, "plan_created"),
        (TaskState.GENERATING, "generation_started"),
        (TaskState.EVALUATING, "generation_completed"),
        (TaskState.AWAITING_SELECTION, "quality_passed"),
        (TaskState.COMPLETED, "candidate_selected"),
    ]:
        runtime.transition(state, event_type=event_type)

    assert runtime.snapshot()["state"] == "completed"
    assert len(runtime.events) == 7
    assert all(event.correlation_id == "task_1" for event in runtime.events)


def test_runtime_rejects_invalid_transition_and_exhausted_retry_budget() -> None:
    runtime = TaskRuntime("task_2", max_retries=1)
    runtime.transition(TaskState.UNDERSTANDING, event_type="understanding_started")
    with pytest.raises(InvalidTransition):
        runtime.transition(TaskState.COMPLETED, event_type="invalid")

    runtime.transition(TaskState.PLANNING, event_type="interpretation_confirmed")
    runtime.transition(TaskState.EXPLORING, event_type="plan_created")
    runtime.transition(TaskState.GENERATING, event_type="generation_started")
    runtime.transition(TaskState.EVALUATING, event_type="generation_completed")
    runtime.transition(TaskState.RETRYING, event_type="quality_failed")
    runtime.transition(TaskState.GENERATING, event_type="retry_started")
    runtime.transition(TaskState.EVALUATING, event_type="generation_completed")
    with pytest.raises(InvalidTransition, match="retry budget exhausted"):
        runtime.transition(TaskState.RETRYING, event_type="quality_failed_again")


def test_runtime_replays_immutable_events() -> None:
    source = TaskRuntime("task_3")
    source.transition(TaskState.UNDERSTANDING, event_type="understanding_started")
    source.transition(TaskState.PLANNING, event_type="interpretation_confirmed")
    source.transition(TaskState.EXPLORING, event_type="plan_created")

    restored = TaskRuntime("task_3")
    restored.replay(source.events)

    assert restored.snapshot() == source.snapshot()
    assert [event.event_type for event in restored.events] == [
        "understanding_started",
        "interpretation_confirmed",
        "plan_created",
    ]
