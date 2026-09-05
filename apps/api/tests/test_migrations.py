"""Alembic migration verification against the isolated PostgreSQL test database."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

TEST_DB_URL = os.environ.get(
    "TEVION_TEST_DB_URL",
    "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion_test",
)
API_DIR = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", TEST_DB_URL)
    os.environ["TEVION_DB_URL"] = TEST_DB_URL
    return config


def _assert_test_database() -> None:
    database_name = urlparse(TEST_DB_URL).path.removeprefix("/")
    if database_name != "tevion_test":
        raise RuntimeError(f"migration tests require tevion_test, got {database_name!r}")


@pytest.fixture()
def migration_database():
    _assert_test_database()
    engine = create_engine(TEST_DB_URL)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        engine.dispose()
        pytest.skip("PostgreSQL unavailable: run `docker compose up -d db` first")

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))

    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()


def test_clean_test_database_upgrades_to_head_and_matches_models(migration_database) -> None:
    command.upgrade(_alembic_config(), "head")

    inspector = inspect(migration_database)
    assert set(inspector.get_table_names()) >= {
        "alembic_version",
        "users",
        "projects",
        "personas",
        "sessions",
        "generation_runs",
        "image_versions",
        "feedback_events",
        "preference_events",
    }


def test_upgraded_test_database_has_no_model_drift(migration_database) -> None:
    command.upgrade(_alembic_config(), "head")
    command.check(_alembic_config())

    with migration_database.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "9d9f5e6a1b2c"
