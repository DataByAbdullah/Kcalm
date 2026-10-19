import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine, get_database_url, get_db


def test_settings_load_database_url() -> None:
    settings = get_settings()

    assert settings.database_url
    assert settings.database_url == get_database_url()
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_session_factory_can_create_session() -> None:
    session = SessionLocal()
    try:
        assert isinstance(session, Session)
        assert session.bind is engine
    finally:
        session.close()


def test_base_metadata_is_available() -> None:
    assert Base.metadata is not None
    assert hasattr(Base.metadata, "tables")


def test_get_db_dependency_yields_and_closes_session() -> None:
    db_generator = get_db()
    session = next(db_generator)

    assert isinstance(session, Session)

    with pytest.raises(StopIteration):
        next(db_generator)


def test_database_connection_when_postgres_is_available() -> None:
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()
    except Exception as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")

    assert result == 1
