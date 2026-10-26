import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa


@pytest.fixture
def migration_context(monkeypatch):
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261026_0019_pre_workout_meal_type.py"
    )
    spec = importlib.util.spec_from_file_location("pre_workout_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE meal_plan_items (meal_type TEXT NOT NULL)"))
            operations = SimpleNamespace(
                get_bind=lambda: connection,
                drop_constraint=Mock(),
                create_check_constraint=Mock(),
            )
            monkeypatch.setattr(migration, "op", operations)
            yield migration, connection, operations
    finally:
        engine.dispose()


def test_downgrade_rejects_pre_workout_before_changing_constraints(migration_context):
    migration, connection, operations = migration_context
    connection.execute(
        sa.text("INSERT INTO meal_plan_items (meal_type) VALUES ('pre_workout'), ('snack')")
    )

    with pytest.raises(RuntimeError, match="pre_workout meal-plan data exists.*before downgrade"):
        migration.downgrade()

    operations.drop_constraint.assert_not_called()
    operations.create_check_constraint.assert_not_called()
    assert connection.execute(sa.text("SELECT meal_type FROM meal_plan_items ORDER BY meal_type")).scalars().all() == [
        "pre_workout", "snack"
    ]


@pytest.mark.parametrize("meal_types", [[], ["breakfast", "lunch", "dinner", "snack"]])
def test_downgrade_without_pre_workout_restores_old_constraint(migration_context, meal_types):
    migration, connection, operations = migration_context
    if meal_types:
        connection.execute(
            sa.text("INSERT INTO meal_plan_items (meal_type) VALUES (:meal_type)"),
            [{"meal_type": meal_type} for meal_type in meal_types],
        )

    migration.downgrade()

    operations.drop_constraint.assert_called_once_with(
        "ck_meal_plan_items_meal_type_valid", "meal_plan_items", type_="check"
    )
    operations.create_check_constraint.assert_called_once_with(
        "ck_meal_plan_items_meal_type_valid", "meal_plan_items",
        "meal_type in ('breakfast', 'lunch', 'dinner', 'snack')",
    )
    assert connection.execute(sa.text("SELECT COUNT(*) FROM meal_plan_items")).scalar() == len(meal_types)
