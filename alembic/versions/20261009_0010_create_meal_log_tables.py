"""create meal log tables

Revision ID: 20261009_0010
Revises: 20261008_0009
Create Date: 2026-10-09 00:10:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261009_0010"
down_revision: str | Sequence[str] | None = "20261008_0009"
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
        "meal_logs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("meal_plan_id", sa.Uuid(), nullable=False),
        sa.Column("meal_plan_item_id", sa.Uuid(), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("log_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("food_id", sa.Uuid(), nullable=True),
        sa.Column("recipe_id", sa.Uuid(), nullable=True),
        sa.Column("quantity_grams", sa.Float(), nullable=True),
        sa.Column("servings", sa.Float(), nullable=True),
        sa.Column("nutrient_complete", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "log_type in ('ate_as_planned', 'corrected')",
            name="ck_meal_logs_log_type_valid",
        ),
        sa.CheckConstraint("status in ('active')", name="ck_meal_logs_status_valid"),
        sa.CheckConstraint(
            "source_type is null or source_type in ('food', 'recipe')",
            name="ck_meal_logs_source_type_valid",
        ),
        sa.CheckConstraint(
            "quantity_grams is null or quantity_grams > 0",
            name="ck_meal_logs_quantity_grams_positive",
        ),
        sa.CheckConstraint(
            "servings is null or servings > 0",
            name="ck_meal_logs_servings_positive",
        ),
        sa.CheckConstraint(
            """
            (log_type = 'ate_as_planned'
                and source_type is null
                and food_id is null
                and recipe_id is null
                and quantity_grams is null
                and servings is null)
            or
            (log_type = 'corrected'
                and source_type = 'food'
                and food_id is not null
                and recipe_id is null
                and quantity_grams is not null
                and servings is null)
            or
            (log_type = 'corrected'
                and source_type = 'recipe'
                and recipe_id is not null
                and food_id is null
                and servings is not null
                and quantity_grams is null)
            """,
            name="ck_meal_logs_type_source_consistent",
        ),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"]),
        sa.ForeignKeyConstraint(["meal_plan_id"], ["meal_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["meal_plan_item_id"],
            ["meal_plan_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_meal_logs_user_id", "meal_logs", ["user_id"], unique=False)
    op.create_index("ix_meal_logs_meal_plan_id", "meal_logs", ["meal_plan_id"], unique=False)
    op.create_index(
        "ix_meal_logs_meal_plan_item_id",
        "meal_logs",
        ["meal_plan_item_id"],
        unique=False,
    )
    op.create_index("ix_meal_logs_log_date", "meal_logs", ["log_date"], unique=False)
    op.create_index("ix_meal_logs_status", "meal_logs", ["status"], unique=False)
    op.create_index(
        "uq_meal_logs_meal_plan_item_id_active",
        "meal_logs",
        ["meal_plan_item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "meal_log_nutrients",
        sa.Column("meal_log_id", sa.Uuid(), nullable=False),
        sa.Column("nutrient_code", sa.String(length=64), nullable=False),
        sa.Column("nutrient_name", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_meal_log_nutrients_amount_non_negative",
        ),
        sa.CheckConstraint(
            "length(btrim(nutrient_code)) > 0",
            name="ck_meal_log_nutrients_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(nutrient_name)) > 0",
            name="ck_meal_log_nutrients_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(unit)) > 0",
            name="ck_meal_log_nutrients_unit_not_blank",
        ),
        sa.ForeignKeyConstraint(["meal_log_id"], ["meal_logs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meal_log_nutrients_meal_log_id",
        "meal_log_nutrients",
        ["meal_log_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_log_nutrients_nutrient_code",
        "meal_log_nutrients",
        ["nutrient_code"],
        unique=False,
    )
    op.create_index(
        "uq_meal_log_nutrients_log_code",
        "meal_log_nutrients",
        ["meal_log_id", "nutrient_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_meal_log_nutrients_log_code", table_name="meal_log_nutrients")
    op.drop_index("ix_meal_log_nutrients_nutrient_code", table_name="meal_log_nutrients")
    op.drop_index("ix_meal_log_nutrients_meal_log_id", table_name="meal_log_nutrients")
    op.drop_table("meal_log_nutrients")

    op.drop_index("uq_meal_logs_meal_plan_item_id_active", table_name="meal_logs")
    op.drop_index("ix_meal_logs_status", table_name="meal_logs")
    op.drop_index("ix_meal_logs_log_date", table_name="meal_logs")
    op.drop_index("ix_meal_logs_meal_plan_item_id", table_name="meal_logs")
    op.drop_index("ix_meal_logs_meal_plan_id", table_name="meal_logs")
    op.drop_index("ix_meal_logs_user_id", table_name="meal_logs")
    op.drop_table("meal_logs")
