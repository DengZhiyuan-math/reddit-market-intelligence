"""Database engine helpers."""

from sqlalchemy import Engine, create_engine

from app.config import Settings


def create_database_engine(settings: Settings | None = None) -> Engine:
    """Create a SQLAlchemy engine from typed application settings."""

    resolved = settings or Settings()
    return create_engine(resolved.database_url, echo=resolved.database_echo)
