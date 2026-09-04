import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tevion_api import models as m
from tevion_api.db import Base

TEST_DB_URL = os.environ.get(
    "TEVION_TEST_DB_URL",
    "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test",
)


def _pg_reachable() -> bool:
    try:
        engine = create_engine(TEST_DB_URL, connect_args={"connect_timeout": 2})
        with engine.connect():
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(),
    reason="PostgreSQL unavailable: run `docker compose up -d db` first",
)


@pytest.fixture(scope="module")
def session() -> Generator[Session, None, None]:
    engine = create_engine(TEST_DB_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_full_chain_roundtrip_on_postgres(session: Session) -> None:
    user = m.User(auth_provider="oidc", provider_subject="sub_abc", email="a@example.com")
    project = m.Project(user=user, name="Portrait Lab")
    persona = m.Persona(project=project, name="Hero A", reference_policy="private")
    gen_session = m.Session(project=project, persona=persona, mode="explore", raw_request="清爽成年男性")
    run = m.GenerationRun(session=gen_session, strategy_version="strategy_v1", provider_name="gpt-image-2")
    image = m.ImageVersion(run=run, asset_uri="s3://tevion/image-1.png", width=1024, height=1280)
    feedback = m.FeedbackEvent(
        user=user,
        session=gen_session,
        image_version=image,
        event_type="selected",
        payload_json={"rating": 5},
    )
    session.add_all([user, project, persona, gen_session, run, image, feedback])
    session.flush()  # assign generated ids before referencing them

    pref = m.PreferenceEvent(
        user=user,
        scope="project",
        scope_id=project.id,
        key="lighting",
        value="soft",
        source="explicit_feedback",
        confidence=0.95,
    )
    session.add(pref)
    session.commit()

    fetched = session.get(m.ImageVersion, image.id)
    assert fetched is not None
    persona_fetched = fetched.run.session.persona
    assert persona_fetched is not None
    assert fetched.run.session.project.user.id == user.id
    assert persona_fetched.name == "Hero A"
    assert fetched.run.strategy_version == "strategy_v1"
    assert fetched.feedback_events[0].payload_json == {"rating": 5}

    stored_pref = session.scalar(select(m.PreferenceEvent).where(m.PreferenceEvent.user_id == user.id))
    assert stored_pref is not None
    assert stored_pref.key == "lighting"
    assert stored_pref.value == "soft"
    assert stored_pref.scope_id == project.id


def test_duplicate_provider_subject_is_rejected(session: Session) -> None:
    session.add(m.User(auth_provider="oidc", provider_subject="dup_sub"))
    session.commit()

    session.add(m.User(auth_provider="oidc", provider_subject="dup_sub"))
    with pytest.raises(Exception):  # IntegrityError from the unique constraint
        session.commit()
    session.rollback()
