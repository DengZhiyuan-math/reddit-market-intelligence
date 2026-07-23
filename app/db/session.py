"""Database session helpers."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.engine import create_database_engine


def create_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Create a SQLAlchemy session factory."""

    resolved_engine = engine or create_database_engine(Settings())
    return sessionmaker(bind=resolved_engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    """Provide a transactional scope around a series of database operations."""

    factory = session_factory or create_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
