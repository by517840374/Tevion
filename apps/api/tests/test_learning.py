from datetime import datetime, timezone

from tevion_api.learning import FeedbackEvidence, PreferenceProjector


def test_explicit_feedback_outweighs_selection() -> None:
    projector = PreferenceProjector()
    events = [
        FeedbackEvidence(
            scope="project", scope_id="p1", key="lighting", value="hard", source="selection"
        ),
        FeedbackEvidence(
            scope="project",
            scope_id="p1",
            key="lighting",
            value="soft",
            source="explicit_feedback",
        ),
    ]

    projection = projector.project(events)

    assert projection[0].value == "soft"
    assert projection[0].weight > projection[1].weight


def test_session_instruction_does_not_update_user_scope() -> None:
    projector = PreferenceProjector()
    events = [
        FeedbackEvidence(
            scope="session",
            scope_id="s1",
            key="background",
            value="simple",
            source="explicit_feedback",
        ),
    ]

    projection = projector.project(events)

    assert projection[0].scope == "session"
    assert all(item.scope != "user" for item in projection)


def test_projection_is_deterministic_and_global_requires_consent() -> None:
    projector = PreferenceProjector()
    events = [
        FeedbackEvidence(
            scope="global", key="lighting", value="soft", source="selection", consented=False
        ),
        FeedbackEvidence(
            scope="global", key="lighting", value="soft", source="selection", consented=True
        ),
    ]

    first = projector.project(events)
    second = projector.project(list(events))

    assert first == second
    assert len(first) == 1
    assert first[0].value == "soft"


def test_deletion_tombstone_removes_preference() -> None:
    projector = PreferenceProjector()
    events = [
        FeedbackEvidence(
            scope="project", scope_id="p1", key="lighting", value="soft", source="selection"
        ),
        FeedbackEvidence(
            scope="project",
            scope_id="p1",
            key="lighting",
            value="soft",
            source="explicit_feedback",
            deleted=True,
        ),
    ]

    assert projector.project(events) == []


def test_preference_projection_metadata_is_stable() -> None:
    projector = PreferenceProjector()
    events = [
        FeedbackEvidence(
            scope="project",
            scope_id="project_1",
            key="lighting",
            value="soft",
            source="explicit_feedback",
        ),
        FeedbackEvidence(
            scope="project",
            scope_id="project_1",
            key="lighting",
            value="soft",
            source="selection",
        ),
    ]

    projection = projector.project(events)

    assert projection[0].scope == "project"
    assert projection[0].scope_id == "project_1"
    assert projection[0].source == "explicit_feedback"
    assert projection[0].evidence_count == 2
    assert projection[0].weight == 1.7
