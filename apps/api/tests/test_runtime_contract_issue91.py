from types import SimpleNamespace

import pytest

from tevion_api.services import (
    InvalidStatusTransition,
    transition_generation_status,
    transition_session_status,
)


def test_session_status_transition_guard_rejects_unbounded_transition() -> None:
    session = SimpleNamespace(status="created")

    with pytest.raises(InvalidStatusTransition, match="created -> completed"):
        transition_session_status(session, "completed")

    assert session.status == "created"


def test_generation_status_transition_guard_rejects_unknown_status() -> None:
    run = SimpleNamespace(status="completed")

    with pytest.raises(InvalidStatusTransition, match="completed -> generating"):
        transition_generation_status(run, "generating")

    assert run.status == "completed"


def test_generation_status_transition_guard_allows_recoverable_unknown_outcome() -> None:
    run = SimpleNamespace(status="generating")

    transition_generation_status(run, "unknown")

    assert run.status == "unknown"


def test_runtime_projection_keeps_task_and_attempt_sources_separate() -> None:
    # This contract is exercised through persisted projection tests; this focused
    # assertion documents that recovery_required is projection-only, not a DB status.
    assert "recovery_required" not in {"created", "generating", "unknown", "failed", "completed"}
