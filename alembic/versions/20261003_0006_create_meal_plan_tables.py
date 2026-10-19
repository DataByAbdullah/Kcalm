"""create meal plan tables

Revision ID: 20261003_0006
Revises: 20261001_0005
Create Date: 2026-10-03 00:06:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261003_0006"
down_revision: str | Sequence[str] | None = "20261001_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "meal_plans",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("solver_status", sa.String(length=32), nullable=False),
        sa.Column("calorie_target", sa.Float(), nullable=False),
        sa.Column("protein_target", sa.Float(), nullable=False),
        sa.Column("carbohydrate_target", sa.Float(), nullable=False),
        sa.Column("fat_target", sa.Float(), nullable=False),
        sa.Column("within_preferred_tolerance", sa.Boolean(), nullable=False),
        sa.Column("objective_value", sa.Integer(), nullable=True),
        sa.Column("solve_time_seconds", sa.Float(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status in ('generated', 'archived')",
            name="ck_meal_plans_status_valid",
        ),
        sa.CheckConstraint(
            "solver_status in ('optimal', 'feasible')",
            name="ck_meal_plans_solver_status_valid",
        ),
        sa.CheckConstraint("calorie_target > 0", name="ck_meal_plans_calorie_target_positive"),
        sa.CheckConstraint("protein_target > 0", name="ck_meal_plans_protein_target_positive"),
        sa.CheckConstraint(
            "carbohydrate_target > 0",
            name="ck_meal_plans_carbohydrate_target_positive",
        ),
        sa.CheckConstraint("fat_target > 0", name="ck_meal_plans_fat_target_positive"),
        sa.CheckConstraint("candidate_count >= 0", name="ck_meal_plans_candidate_count_non_negative"),
        sa.CheckConstraint(
            "solve_time_seconds >= 0",
            name="ck_meal_plans_solve_time_non_negative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meal_plans_user_id", "meal_plans", ["user_id"], unique=False)
    op.create_index("ix_meal_plans_plan_date", "meal_plans", ["plan_date"], unique=False)
    op.create_index("ix_meal_plans_status", "meal_plans", ["status"], unique=False)
    op.create_index(
        "uq_meal_plans_user_id_plan_date_generated",
        "meal_plans",
        ["user_id", "plan_date"],
        unique=True,
        postgresql_where=sa.text("status = 'generated'"),
    )

    op.create_table(
        "meal_plan_items",
        sa.Column("meal_plan_id", sa.Uuid(), nullable=False),
        sa.Column("meal_type", sa.String(length=32), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("recipe_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("servings", sa.Float(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "meal_type in ('breakfast', 'lunch', 'dinner', 'snack')",
            name="ck_meal_plan_items_meal_type_valid",
        ),
        sa.CheckConstraint("servings > 0", name="ck_meal_plan_items_servings_positive"),
        sa.CheckConstraint("position > 0", name="ck_meal_plan_items_position_positive"),
        sa.CheckConstraint(
            "length(btrim(recipe_name_snapshot)) > 0",
            name="ck_meal_plan_items_recipe_name_not_blank",
        ),
        sa.ForeignKeyConstraint(["meal_plan_id"], ["meal_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meal_plan_id", "position", name="uq_meal_plan_items_plan_position"),
    )
    op.create_index("ix_meal_plan_items_meal_plan_id", "meal_plan_items", ["meal_plan_id"], unique=False)
    op.create_index("ix_meal_plan_items_recipe_id", "meal_plan_items", ["recipe_id"], unique=False)

    op.create_table(
        "meal_plan_item_nutrients",
        sa.Column("meal_plan_item_id", sa.Uuid(), nullable=False),
        sa.Column("nutrient_code", sa.String(length=64), nullable=False),
        sa.Column("nutrient_name", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("amount >= 0", name="ck_meal_plan_item_nutrients_amount_non_negative"),
        sa.CheckConstraint(
            "length(btrim(nutrient_code)) > 0",
            name="ck_meal_plan_item_nutrients_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(nutrient_name)) > 0",
            name="ck_meal_plan_item_nutrients_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(unit)) > 0",
            name="ck_meal_plan_item_nutrients_unit_not_blank",
        ),
        sa.ForeignKeyConstraint(["meal_plan_item_id"], ["meal_plan_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meal_plan_item_id",
            "nutrient_code",
            name="uq_meal_plan_item_nutrients_item_code",
        ),
    )
    op.create_index(
        "ix_meal_plan_item_nutrients_item_id",
        "meal_plan_item_nutrients",
        ["meal_plan_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plan_item_nutrients_nutrient_code",
        "meal_plan_item_nutrients",
        ["nutrient_code"],
        unique=False,
    )

    op.create_table(
        "meal_plan_micronutrient_targets",
        sa.Column("meal_plan_id", sa.Uuid(), nullable=False),
        sa.Column("nutrient_code", sa.String(length=64), nullable=False),
        sa.Column("nutrient_name", sa.String(length=128), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("minimum_target", sa.Float(), nullable=True),
        sa.Column("upper_limit", sa.Float(), nullable=True),
        sa.Column("upper_limit_type", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("target > 0", name="ck_meal_plan_micro_targets_target_positive"),
        sa.CheckConstraint(
            "minimum_target is null or minimum_target > 0",
            name="ck_meal_plan_micro_targets_minimum_positive",
        ),
        sa.CheckConstraint(
            "upper_limit is null or upper_limit > 0",
            name="ck_meal_plan_micro_targets_upper_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(nutrient_code)) > 0",
            name="ck_meal_plan_micro_targets_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(nutrient_name)) > 0",
            name="ck_meal_plan_micro_targets_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(unit)) > 0",
            name="ck_meal_plan_micro_targets_unit_not_blank",
        ),
        sa.ForeignKeyConstraint(["meal_plan_id"], ["meal_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meal_plan_id",
            "nutrient_code",
            name="uq_meal_plan_micro_targets_plan_code",
        ),
    )
    op.create_index(
        "ix_meal_plan_micro_targets_meal_plan_id",
        "meal_plan_micronutrient_targets",
        ["meal_plan_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plan_micro_targets_nutrient_code",
        "meal_plan_micronutrient_targets",
        ["nutrient_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meal_plan_micro_targets_nutrient_code",
        table_name="meal_plan_micronutrient_targets",
    )
    op.drop_index(
        "ix_meal_plan_micro_targets_meal_plan_id",
        table_name="meal_plan_micronutrient_targets",
    )
    op.drop_table("meal_plan_micronutrient_targets")
    op.drop_index(
        "ix_meal_plan_item_nutrients_nutrient_code",
        table_name="meal_plan_item_nutrients",
    )
    op.drop_index(
        "ix_meal_plan_item_nutrients_item_id",
        table_name="meal_plan_item_nutrients",
    )
    op.drop_table("meal_plan_item_nutrients")
    op.drop_index("ix_meal_plan_items_recipe_id", table_name="meal_plan_items")
    op.drop_index("ix_meal_plan_items_meal_plan_id", table_name="meal_plan_items")
    op.drop_table("meal_plan_items")
    op.drop_index("uq_meal_plans_user_id_plan_date_generated", table_name="meal_plans")
    op.drop_index("ix_meal_plans_status", table_name="meal_plans")
    op.drop_index("ix_meal_plans_plan_date", table_name="meal_plans")
    op.drop_index("ix_meal_plans_user_id", table_name="meal_plans")
    op.drop_table("meal_plans")
