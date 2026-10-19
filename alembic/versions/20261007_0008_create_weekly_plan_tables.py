"""create weekly plan tables

Revision ID: 20261007_0008
Revises: 20261003_0007
Create Date: 2026-10-07 00:08:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261007_0008"
down_revision: str | Sequence[str] | None = "20261003_0007"
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
        "weekly_meal_plans",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status in ('generated', 'archived')",
            name="ck_weekly_meal_plans_status_valid",
        ),
        sa.CheckConstraint(
            "end_date >= start_date",
            name="ck_weekly_meal_plans_end_after_start",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_weekly_meal_plans_user_id",
        "weekly_meal_plans",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_weekly_meal_plans_start_date",
        "weekly_meal_plans",
        ["start_date"],
        unique=False,
    )
    op.create_index(
        "ix_weekly_meal_plans_end_date",
        "weekly_meal_plans",
        ["end_date"],
        unique=False,
    )
    op.create_index(
        "ix_weekly_meal_plans_status",
        "weekly_meal_plans",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_weekly_meal_plans_user_range_generated",
        "weekly_meal_plans",
        ["user_id", "start_date", "end_date"],
        unique=True,
        postgresql_where=sa.text("status = 'generated'"),
    )

    op.add_column(
        "meal_plans",
        sa.Column("weekly_plan_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_meal_plans_weekly_plan_id",
        "meal_plans",
        ["weekly_plan_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_meal_plans_weekly_plan_id_weekly_meal_plans",
        "meal_plans",
        "weekly_meal_plans",
        ["weekly_plan_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "meal_plan_item_ingredients",
        sa.Column("meal_plan_item_id", sa.Uuid(), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("food_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("quantity_grams", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "quantity_grams > 0",
            name="ck_meal_plan_item_ingredients_quantity_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(food_name_snapshot)) > 0",
            name="ck_meal_plan_item_ingredients_food_name_not_blank",
        ),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"]),
        sa.ForeignKeyConstraint(
            ["meal_plan_item_id"],
            ["meal_plan_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "meal_plan_item_id",
            "food_id",
            name="uq_meal_plan_item_ingredients_item_food",
        ),
    )
    op.create_index(
        "ix_meal_plan_item_ingredients_item_id",
        "meal_plan_item_ingredients",
        ["meal_plan_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plan_item_ingredients_food_id",
        "meal_plan_item_ingredients",
        ["food_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meal_plan_item_ingredients_food_id",
        table_name="meal_plan_item_ingredients",
    )
    op.drop_index(
        "ix_meal_plan_item_ingredients_item_id",
        table_name="meal_plan_item_ingredients",
    )
    op.drop_table("meal_plan_item_ingredients")

    op.drop_constraint(
        "fk_meal_plans_weekly_plan_id_weekly_meal_plans",
        "meal_plans",
        type_="foreignkey",
    )
    op.drop_index("ix_meal_plans_weekly_plan_id", table_name="meal_plans")
    op.drop_column("meal_plans", "weekly_plan_id")

    op.drop_index(
        "uq_weekly_meal_plans_user_range_generated",
        table_name="weekly_meal_plans",
    )
    op.drop_index("ix_weekly_meal_plans_status", table_name="weekly_meal_plans")
    op.drop_index("ix_weekly_meal_plans_end_date", table_name="weekly_meal_plans")
    op.drop_index("ix_weekly_meal_plans_start_date", table_name="weekly_meal_plans")
    op.drop_index("ix_weekly_meal_plans_user_id", table_name="weekly_meal_plans")
    op.drop_table("weekly_meal_plans")
