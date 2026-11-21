import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.core.database import engine


def test_outbox_migration_preserves_users_and_supports_rollback(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261120_0025_password_reset_jobs.py"
    spec = importlib.util.spec_from_file_location("reset_jobs_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261120_0025"
    assert migration.down_revision == "20261118_0024"
    schema = "reset_migration_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            connection.exec_driver_sql("CREATE TABLE users (id UUID PRIMARY KEY, email TEXT NOT NULL)")
            identity = uuid4()
            connection.execute(text("INSERT INTO users VALUES (:id,'existing@example.com')"), {"id": identity})
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            columns = {column["name"] for column in inspect(connection).get_columns("password_reset_jobs", schema=schema)}
            assert columns == {"id", "created_at", "updated_at", "user_id", "password_fingerprint", "status",
                               "attempts", "available_at", "expires_at", "lease_id", "lease_until", "failure_category"}
            assert not {"email", "token", "password_hash", "api_key"} & columns
            connection.execute(text("""INSERT INTO password_reset_jobs
                (id,user_id,password_fingerprint,status,attempts,available_at,expires_at)
                VALUES (:id,:user_id,:fingerprint,'pending',0,now(),now()+interval '30 minutes')"""),
                {"id": uuid4(), "user_id": identity, "fingerprint": "a" * 64})
            assert connection.scalar(text("SELECT count(*) FROM password_reset_jobs")) == 1
            connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": identity})
            assert connection.scalar(text("SELECT count(*) FROM password_reset_jobs")) == 0
            connection.execute(text("INSERT INTO users VALUES (:id,'preserved@example.com')"), {"id": identity})
            migration.downgrade()
            assert not inspect(connection).has_table("password_reset_jobs", schema=schema)
            assert connection.scalar(text("SELECT email FROM users")) == "preserved@example.com"
            migration.upgrade()
            assert connection.scalar(text("SELECT count(*) FROM users")) == 1
            assert connection.scalar(text("SELECT count(*) FROM password_reset_jobs")) == 0
        finally:
            transaction.rollback()
