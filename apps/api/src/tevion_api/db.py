"""Database engine and session factory.

The URL is read from TEVION_DB_URL and defaults to the local docker-compose
PostgreSQL instance so a plain `docker compose up -d` is enough to develop.
"""

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DB_URL = "postgresql+psycopg://tevion:tevion_dev@localhost:5432/tevion"

engine = create_engine(os.environ.get("TEVION_DB_URL", DEFAULT_DB_URL), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
