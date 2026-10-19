"""create food tables

Revision ID: 20260929_0004
Revises: 20260929_0003
Create Date: 2026-09-29 00:30:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260929_0004"
down_revision: str | Sequence[str] | None = "20260929_0003"
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
        "foods",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_food_id", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("source in ('internal', 'usda', 'licensed')", name="ck_foods_source_valid"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_foods_name_not_blank"),
        sa.CheckConstraint("length(btrim(category)) > 0", name="ck_foods_category_not_blank"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_food_id", name="uq_foods_source_source_food_id"),
    )
    op.create_index("ix_foods_name", "foods", ["name"], unique=False)
    op.create_index("ix_foods_category", "foods", ["category"], unique=False)

    op.create_table(
        "food_nutrients",
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("nutrient_code", sa.String(length=64), nullable=False),
        sa.Column("nutrient_name", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("amount >= 0", name="ck_food_nutrients_amount_non_negative"),
        sa.CheckConstraint(
            "length(btrim(nutrient_code)) > 0",
            name="ck_food_nutrients_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(nutrient_name)) > 0",
            name="ck_food_nutrients_name_not_blank",
        ),
        sa.CheckConstraint("length(btrim(unit)) > 0", name="ck_food_nutrients_unit_not_blank"),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("food_id", "nutrient_code", name="uq_food_nutrients_food_id_code"),
    )
    op.create_index("ix_food_nutrients_food_id", "food_nutrients", ["food_id"], unique=False)
    op.create_index(
        "ix_food_nutrients_nutrient_code",
        "food_nutrients",
        ["nutrient_code"],
        unique=False,
    )

    op.create_table(
        "food_servings",
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("serving_name", sa.String(length=128), nullable=False),
        sa.Column("grams", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("grams > 0", name="ck_food_servings_grams_positive"),
        sa.CheckConstraint(
            "length(btrim(serving_name)) > 0",
            name="ck_food_servings_name_not_blank",
        ),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("food_id", "serving_name", name="uq_food_servings_food_id_name"),
    )
    op.create_index("ix_food_servings_food_id", "food_servings", ["food_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_food_servings_food_id", table_name="food_servings")
    op.drop_table("food_servings")
    op.drop_index("ix_food_nutrients_nutrient_code", table_name="food_nutrients")
    op.drop_index("ix_food_nutrients_food_id", table_name="food_nutrients")
    op.drop_table("food_nutrients")
    op.drop_index("ix_foods_category", table_name="foods")
    op.drop_index("ix_foods_name", table_name="foods")
    op.drop_table("foods")
