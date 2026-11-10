import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.core.database import engine


def test_recipe_image_migration_backfills_checks_status_and_downgrades(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261110_0023_recipe_images.py"
    spec = importlib.util.spec_from_file_location("recipe_image_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261105_0022"
    schema = "image_migration_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            connection.exec_driver_sql("CREATE TABLE recipes (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
            connection.exec_driver_sql("INSERT INTO recipes (id, name) VALUES (1, 'Existing recipe')")
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            row = connection.execute(text("SELECT * FROM recipes WHERE id = 1")).mappings().one()
            assert row["name"] == "Existing recipe" and row["image_status"] == "missing"
            assert all(value is None for key, value in row.items() if key.startswith("image_") and key != "image_status")
            connection.exec_driver_sql("INSERT INTO recipes (id, name) VALUES (2, 'New recipe')")
            assert connection.scalar(text("SELECT image_status FROM recipes WHERE id = 2")) == "missing"
            for value in ("missing", "generating", "ready", "failed"):
                connection.execute(text("UPDATE recipes SET image_status = :status WHERE id = 1"), {"status": value})
            for statement in (
                "UPDATE recipes SET image_status = 'invalid' WHERE id = 1",
                "UPDATE recipes SET image_status = NULL WHERE id = 1",
            ):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.exec_driver_sql(statement)
            columns = {column["name"]: column for column in inspect(connection).get_columns("recipes", schema=schema)}
            assert columns["image_status"]["nullable"] is False
            assert columns["image_generated_at"]["type"].timezone is True
            assert columns["image_generation_started_at"]["type"].timezone is True
            assert all(column["nullable"] for name, column in columns.items() if name.startswith("image_") and name != "image_status")
            migration.downgrade()
            assert {column["name"] for column in inspect(connection).get_columns("recipes", schema=schema)} == {"id", "name"}
            assert connection.scalar(text("SELECT COUNT(*) FROM recipes")) == 2
            migration.upgrade()
            assert connection.scalar(text("SELECT COUNT(*) FROM recipes WHERE image_status = 'missing'")) == 2
        finally:
            transaction.rollback()
