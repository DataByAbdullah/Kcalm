import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text, Text

from app.core.database import engine


def test_migration_preserves_users_and_supports_upgrade_downgrade(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261118_0024_user_avatar.py"
    spec = importlib.util.spec_from_file_location("user_avatar_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261118_0024" and migration.down_revision == "20261110_0023"
    schema = "avatar_migration_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL, full_name TEXT)")
            connection.exec_driver_sql("INSERT INTO users VALUES (1, 'existing@example.com', 'Existing User')")
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            row = connection.execute(text("SELECT * FROM users WHERE id = 1")).mappings().one()
            assert dict(row) == {"id": 1, "email": "existing@example.com", "full_name": "Existing User", "avatar_data_url": None}
            columns = {c["name"]: c for c in inspect(connection).get_columns("users", schema=schema)}
            assert isinstance(columns["avatar_data_url"]["type"], Text) and columns["avatar_data_url"]["nullable"]
            connection.exec_driver_sql("INSERT INTO users (id, email) VALUES (2, 'new@example.com')")
            assert connection.scalar(text("SELECT avatar_data_url FROM users WHERE id = 2")) is None
            connection.exec_driver_sql("UPDATE users SET avatar_data_url = 'stored avatar' WHERE id = 1")
            migration.downgrade()
            assert {c["name"] for c in inspect(connection).get_columns("users", schema=schema)} == {"id", "email", "full_name"}
            assert connection.execute(text("SELECT id, email, full_name FROM users ORDER BY id")).all() == [
                (1, "existing@example.com", "Existing User"), (2, "new@example.com", None)]
            migration.upgrade()
            assert connection.scalar(text("SELECT COUNT(*) FROM users WHERE avatar_data_url IS NULL")) == 2
        finally:
            transaction.rollback()
