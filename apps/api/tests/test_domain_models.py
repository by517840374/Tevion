from tevion_api.domain import (
    FeedbackEvent,
    GenerationRun,
    ImageVersion,
    PreferenceEvent,
    Project,
    Session,
)


def test_project_session_and_generation_are_linked_by_ids() -> None:
    project = Project(id="project_1", user_id="user_1", name="Portrait Lab")
    session = Session(id="session_1", project_id=project.id, mode="explore")
    run = GenerationRun(id="run_1", session_id=session.id, strategy_version="strategy_v1")
    image = ImageVersion(id="image_1", run_id=run.id, asset_uri="assets/image_1.png")

    assert session.project_id == project.id
    assert run.session_id == session.id
    assert image.run_id == run.id


def test_feedback_event_carries_user_decision_and_image_reference() -> None:
    event = FeedbackEvent(
        id="event_1",
        user_id="user_1",
        session_id="session_1",
        image_version_id="image_1",
        event_type="selected",
        payload={"rating": 5},
    )

    assert event.event_type == "selected"
    assert event.image_version_id == "image_1"
    assert event.payload["rating"] == 5


def test_preference_event_has_scope_and_evidence_source() -> None:
    event = PreferenceEvent(
        id="pref_event_1",
        user_id="user_1",
        scope="project",
        scope_id="project_1",
        key="lighting",
        value="soft_directional",
        source="explicit_feedback",
        confidence=0.95,
    )

    assert event.scope == "project"
    assert event.source == "explicit_feedback"
    assert event.confidence == 0.95
