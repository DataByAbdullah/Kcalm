from datetime import time
import importlib.util
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.database import engine


def test_profile_schedule_migration_backfills_clamps_and_keeps_old_plan_times_null(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261105_0022_profile_meal_schedule.py"
    spec = importlib.util.spec_from_file_location("profile_meal_schedule_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    schema = "schedule_migration_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            # Exercise real PostgreSQL DDL against old-shaped tables in a private
            # schema; rolling back also removes this schema and all test data.
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            connection.exec_driver_sql("CREATE TABLE user_profiles (id INTEGER PRIMARY KEY, meals_per_day INTEGER NOT NULL)")
            connection.exec_driver_sql("CREATE TABLE meal_plan_items (id INTEGER PRIMARY KEY)")
            connection.execute(text("INSERT INTO user_profiles (id, meals_per_day) VALUES (:id, :count)"),
                               [{"id": index, "count": count} for index, count in enumerate([-2, 1, 2, 3, 5, 8], 1)])
            connection.exec_driver_sql("INSERT INTO meal_plan_items (id) VALUES (1)")
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))

            migration.upgrade()

            rows = connection.execute(text("SELECT * FROM user_profiles ORDER BY id")).mappings().all()
            assert [row["meals_per_day"] for row in rows] == [2, 2, 2, 3, 5, 5]
            for row in rows:
                assert row["usual_wake_time"] == time(7)
                assert row["usual_sleep_time"] == time(23)
                assert row["timezone"] == "UTC"
            assert connection.scalar(text("SELECT scheduled_time FROM meal_plan_items WHERE id = 1")) is None
            columns = {column["name"]: column for column in inspect(connection).get_columns("user_profiles", schema=schema)}
            assert all(columns[name]["nullable"] is False for name in ("usual_wake_time", "usual_sleep_time", "timezone"))
            assert inspect(connection).get_columns("meal_plan_items", schema=schema)[1]["nullable"] is True
            for statement in (
                "UPDATE user_profiles SET meals_per_day = 1 WHERE id = 1",
                "UPDATE user_profiles SET meals_per_day = 6 WHERE id = 1",
                "UPDATE user_profiles SET usual_wake_time = usual_sleep_time WHERE id = 1",
                "UPDATE user_profiles SET timezone = NULL WHERE id = 1",
            ):
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        connection.exec_driver_sql(statement)

            migration.downgrade()
            assert {column["name"] for column in inspect(connection).get_columns("user_profiles", schema=schema)} == {"id", "meals_per_day"}
            assert {column["name"] for column in inspect(connection).get_columns("meal_plan_items", schema=schema)} == {"id"}
            migration.upgrade()
            assert connection.scalar(text("SELECT COUNT(*) FROM user_profiles WHERE timezone = 'UTC'")) == 6
        finally:
            transaction.rollback()
