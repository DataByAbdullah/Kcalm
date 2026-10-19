"""create recipe tables

Revision ID: 20261001_0005
Revises: 20260929_0004
Create Date: 2026-10-01 00:05:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261001_0005"
down_revision: str | Sequence[str] | None = "20260929_0004"
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
        "recipes",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("servings", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("prep_time_minutes", sa.Integer(), nullable=False),
        sa.Column("cook_time_minutes", sa.Integer(), nullable=False),
        sa.Column("total_time_minutes", sa.Integer(), nullable=False),
        sa.Column("difficulty", sa.String(length=64), nullable=True),
        sa.Column("instructions_summary", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_recipes_name_not_blank"),
        sa.CheckConstraint("servings > 0", name="ck_recipes_servings_positive"),
        sa.CheckConstraint("prep_time_minutes >= 0", name="ck_recipes_prep_time_non_negative"),
        sa.CheckConstraint("cook_time_minutes >= 0", name="ck_recipes_cook_time_non_negative"),
        sa.CheckConstraint("total_time_minutes >= 0", name="ck_recipes_total_time_non_negative"),
        sa.CheckConstraint(
            "total_time_minutes = prep_time_minutes + cook_time_minutes",
            name="ck_recipes_total_time_matches_parts",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recipes_name", "recipes", ["name"], unique=False)
    op.create_index("ix_recipes_active", "recipes", ["active"], unique=False)
    op.create_index("ix_recipes_total_time_minutes", "recipes", ["total_time_minutes"], unique=False)

    op.create_table(
        "recipe_tags",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_recipe_tags_name_not_blank"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_recipe_tags_name"),
    )
    op.create_index("ix_recipe_tags_name", "recipe_tags", ["name"], unique=False)

    op.create_table(
        "recipe_ingredients",
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_grams", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("display_quantity", sa.String(length=64), nullable=True),
        sa.Column("display_unit", sa.String(length=64), nullable=True),
        sa.Column("preparation_note", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("quantity_grams > 0", name="ck_recipe_ingredients_quantity_positive"),
        sa.CheckConstraint("position > 0", name="ck_recipe_ingredients_position_positive"),
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"]),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "position", name="uq_recipe_ingredients_recipe_id_position"),
    )
    op.create_index("ix_recipe_ingredients_recipe_id", "recipe_ingredients", ["recipe_id"], unique=False)
    op.create_index("ix_recipe_ingredients_food_id", "recipe_ingredients", ["food_id"], unique=False)

    op.create_table(
        "recipe_steps",
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("timer", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("position > 0", name="ck_recipe_steps_position_positive"),
        sa.CheckConstraint("length(btrim(instruction)) > 0", name="ck_recipe_steps_instruction_not_blank"),
        sa.CheckConstraint(
            "duration_seconds is null or duration_seconds >= 0",
            name="ck_recipe_steps_duration_non_negative",
        ),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "position", name="uq_recipe_steps_recipe_id_position"),
    )
    op.create_index("ix_recipe_steps_recipe_id", "recipe_steps", ["recipe_id"], unique=False)

    op.create_table(
        "recipe_tag_links",
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["recipe_tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "tag_id", name="uq_recipe_tag_links_recipe_id_tag_id"),
    )
    op.create_index("ix_recipe_tag_links_recipe_id", "recipe_tag_links", ["recipe_id"], unique=False)
    op.create_index("ix_recipe_tag_links_tag_id", "recipe_tag_links", ["tag_id"], unique=False)

    op.create_table(
        "recipe_equipment",
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("equipment", sa.String(length=128), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("length(btrim(equipment)) > 0", name="ck_recipe_equipment_not_blank"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "equipment", name="uq_recipe_equipment_recipe_id_equipment"),
    )
    op.create_index("ix_recipe_equipment_recipe_id", "recipe_equipment", ["recipe_id"], unique=False)
    op.create_index("ix_recipe_equipment_equipment", "recipe_equipment", ["equipment"], unique=False)

    op.create_table(
        "recipe_nutrients",
        sa.Column("recipe_id", sa.Uuid(), nullable=False),
        sa.Column("nutrient_code", sa.String(length=64), nullable=False),
        sa.Column("nutrient_name", sa.String(length=128), nullable=False),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("per_serving_amount", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("missing_ingredient_count", sa.Integer(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint("total_amount >= 0", name="ck_recipe_nutrients_total_amount_non_negative"),
        sa.CheckConstraint(
            "per_serving_amount >= 0",
            name="ck_recipe_nutrients_per_serving_amount_non_negative",
        ),
        sa.CheckConstraint("missing_ingredient_count >= 0", name="ck_recipe_nutrients_missing_count_non_negative"),
        sa.CheckConstraint("length(btrim(nutrient_code)) > 0", name="ck_recipe_nutrients_code_not_blank"),
        sa.CheckConstraint("length(btrim(nutrient_name)) > 0", name="ck_recipe_nutrients_name_not_blank"),
        sa.CheckConstraint("length(btrim(unit)) > 0", name="ck_recipe_nutrients_unit_not_blank"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "nutrient_code", name="uq_recipe_nutrients_recipe_id_code"),
    )
    op.create_index("ix_recipe_nutrients_recipe_id", "recipe_nutrients", ["recipe_id"], unique=False)
    op.create_index("ix_recipe_nutrients_nutrient_code", "recipe_nutrients", ["nutrient_code"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_recipe_nutrients_nutrient_code", table_name="recipe_nutrients")
    op.drop_index("ix_recipe_nutrients_recipe_id", table_name="recipe_nutrients")
    op.drop_table("recipe_nutrients")
    op.drop_index("ix_recipe_equipment_equipment", table_name="recipe_equipment")
    op.drop_index("ix_recipe_equipment_recipe_id", table_name="recipe_equipment")
    op.drop_table("recipe_equipment")
    op.drop_index("ix_recipe_tag_links_tag_id", table_name="recipe_tag_links")
    op.drop_index("ix_recipe_tag_links_recipe_id", table_name="recipe_tag_links")
    op.drop_table("recipe_tag_links")
    op.drop_index("ix_recipe_steps_recipe_id", table_name="recipe_steps")
    op.drop_table("recipe_steps")
    op.drop_index("ix_recipe_ingredients_food_id", table_name="recipe_ingredients")
    op.drop_index("ix_recipe_ingredients_recipe_id", table_name="recipe_ingredients")
    op.drop_table("recipe_ingredients")
    op.drop_index("ix_recipe_tags_name", table_name="recipe_tags")
    op.drop_table("recipe_tags")
    op.drop_index("ix_recipes_total_time_minutes", table_name="recipes")
    op.drop_index("ix_recipes_active", table_name="recipes")
    op.drop_index("ix_recipes_name", table_name="recipes")
    op.drop_table("recipes")
