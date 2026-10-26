"""Allow pre_workout in persisted meal items, retaining snack.

Revision ID: 20261026_0019
Revises: 20261021_0018
"""
from alembic import op
import sqlalchemy as sa

revision = "20261026_0019"
down_revision = "20261021_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_meal_plan_items_meal_type_valid", "meal_plan_items", type_="check")
    op.create_check_constraint("ck_meal_plan_items_meal_type_valid", "meal_plan_items",
        "meal_type in ('breakfast', 'lunch', 'pre_workout', 'dinner', 'snack')")


def downgrade():
    has_pre_workout = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM meal_plan_items WHERE meal_type = 'pre_workout')")
    ).scalar()
    if has_pre_workout:
        raise RuntimeError(
            "Cannot downgrade 20261026_0019: pre_workout meal-plan data exists. "
            "Remove or explicitly handle all pre_workout meal_plan_items before downgrade."
        )
    op.drop_constraint("ck_meal_plan_items_meal_type_valid", "meal_plan_items", type_="check")
    op.create_check_constraint("ck_meal_plan_items_meal_type_valid", "meal_plan_items",
        "meal_type in ('breakfast', 'lunch', 'dinner', 'snack')")
