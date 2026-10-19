"""create grocery list tables

Revision ID: 20261008_0009
Revises: 20261007_0008
Create Date: 2026-10-08 00:09:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261008_0009"
down_revision: str | Sequence[str] | None = "20261007_0008"
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
        "grocery_lists",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("weekly_plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status in ('active', 'archived')",
            name="ck_grocery_lists_status_valid",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["weekly_plan_id"],
            ["weekly_meal_plans.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_grocery_lists_user_id", "grocery_lists", ["user_id"], unique=False)
    op.create_index(
        "ix_grocery_lists_weekly_plan_id",
        "grocery_lists",
        ["weekly_plan_id"],
        unique=False,
    )
    op.create_index("ix_grocery_lists_status", "grocery_lists", ["status"], unique=False)
    op.create_index(
        "uq_grocery_lists_weekly_plan_id_active",
        "grocery_lists",
        ["weekly_plan_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "grocery_list_items",
        sa.Column("grocery_list_id", sa.Uuid(), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=True),
        sa.Column("food_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("quantity_grams", sa.Float(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("checked", sa.Boolean(), nullable=False),
        sa.Column("manually_added", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("quantity > 0", name="ck_grocery_list_items_quantity_positive"),
        sa.CheckConstraint(
            "quantity_grams is null or quantity_grams > 0",
            name="ck_grocery_list_items_quantity_grams_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(food_name_snapshot)) > 0",
            name="ck_grocery_list_items_food_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(unit)) > 0",
            name="ck_grocery_list_items_unit_not_blank",
        ),
        sa.CheckConstraint(
            "category in ('produce', 'meat_seafood', 'dairy', 'grains', 'pantry', 'frozen', 'other')",
            name="ck_grocery_list_items_category_valid",
        ),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"]),
        sa.ForeignKeyConstraint(
            ["grocery_list_id"],
            ["grocery_lists.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_grocery_list_items_grocery_list_id",
        "grocery_list_items",
        ["grocery_list_id"],
        unique=False,
    )
    op.create_index(
        "ix_grocery_list_items_food_id",
        "grocery_list_items",
        ["food_id"],
        unique=False,
    )
    op.create_index(
        "ix_grocery_list_items_category",
        "grocery_list_items",
        ["category"],
        unique=False,
    )
    op.create_index(
        "ix_grocery_list_items_checked",
        "grocery_list_items",
        ["checked"],
        unique=False,
    )
    op.create_index(
        "uq_grocery_list_items_list_food_generated",
        "grocery_list_items",
        ["grocery_list_id", "food_id"],
        unique=True,
        postgresql_where=sa.text("food_id is not null and manually_added = false"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_grocery_list_items_list_food_generated",
        table_name="grocery_list_items",
    )
    op.drop_index("ix_grocery_list_items_checked", table_name="grocery_list_items")
    op.drop_index("ix_grocery_list_items_category", table_name="grocery_list_items")
    op.drop_index("ix_grocery_list_items_food_id", table_name="grocery_list_items")
    op.drop_index(
        "ix_grocery_list_items_grocery_list_id",
        table_name="grocery_list_items",
    )
    op.drop_table("grocery_list_items")

    op.drop_index("uq_grocery_lists_weekly_plan_id_active", table_name="grocery_lists")
    op.drop_index("ix_grocery_lists_status", table_name="grocery_lists")
    op.drop_index("ix_grocery_lists_weekly_plan_id", table_name="grocery_lists")
    op.drop_index("ix_grocery_lists_user_id", table_name="grocery_lists")
    op.drop_table("grocery_lists")
