"""create meal plan adaptation snapshots

Revision ID: 20261010_0011
Revises: 20261009_0010
Create Date: 2026-10-10 00:11:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261010_0011"
down_revision: str | Sequence[str] | None = "20261009_0010"
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
        "meal_plan_adaptations",
        sa.Column("meal_plan_id", sa.Uuid(), nullable=False),
        sa.Column("source_meal_plan_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("base_calorie_target", sa.Float(), nullable=False),
        sa.Column("source_actual_calories", sa.Float(), nullable=False),
        sa.Column("source_calorie_deviation", sa.Float(), nullable=False),
        sa.Column("compensation_fraction", sa.Float(), nullable=False),
        sa.Column("compensation_amount", sa.Float(), nullable=False),
        sa.Column("adjusted_calorie_target", sa.Float(), nullable=False),
        sa.Column("base_protein_target", sa.Float(), nullable=False),
        sa.Column("base_carbohydrate_target", sa.Float(), nullable=False),
        sa.Column("base_fat_target", sa.Float(), nullable=False),
        sa.Column("adjusted_protein_target", sa.Float(), nullable=False),
        sa.Column("adjusted_carbohydrate_target", sa.Float(), nullable=False),
        sa.Column("adjusted_fat_target", sa.Float(), nullable=False),
        sa.Column("safety_cap_applied", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "length(btrim(policy_version)) > 0",
            name="ck_meal_plan_adaptations_policy_version_not_blank",
        ),
        sa.CheckConstraint(
            "base_calorie_target > 0",
            name="ck_meal_plan_adaptations_base_calorie_positive",
        ),
        sa.CheckConstraint(
            "adjusted_calorie_target > 0",
            name="ck_meal_plan_adaptations_adjusted_calorie_positive",
        ),
        sa.CheckConstraint(
            "compensation_fraction >= 0 and compensation_fraction <= 1",
            name="ck_meal_plan_adaptations_fraction_range",
        ),
        sa.CheckConstraint(
            "base_protein_target > 0",
            name="ck_meal_plan_adaptations_base_protein_positive",
        ),
        sa.CheckConstraint(
            "base_carbohydrate_target >= 0",
            name="ck_meal_plan_adaptations_base_carbs_non_negative",
        ),
        sa.CheckConstraint(
            "base_fat_target > 0",
            name="ck_meal_plan_adaptations_base_fat_positive",
        ),
        sa.CheckConstraint(
            "adjusted_protein_target > 0",
            name="ck_meal_plan_adaptations_adjusted_protein_positive",
        ),
        sa.CheckConstraint(
            "adjusted_carbohydrate_target >= 0",
            name="ck_meal_plan_adaptations_adjusted_carbs_non_negative",
        ),
        sa.CheckConstraint(
            "adjusted_fat_target > 0",
            name="ck_meal_plan_adaptations_adjusted_fat_positive",
        ),
        sa.ForeignKeyConstraint(["meal_plan_id"], ["meal_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_meal_plan_id"], ["meal_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_meal_plan_adaptations_meal_plan_id",
        "meal_plan_adaptations",
        ["meal_plan_id"],
        unique=True,
    )
    op.create_index(
        "ix_meal_plan_adaptations_source_meal_plan_id",
        "meal_plan_adaptations",
        ["source_meal_plan_id"],
        unique=False,
    )
    op.create_index(
        "ix_meal_plan_adaptations_policy_version",
        "meal_plan_adaptations",
        ["policy_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_meal_plan_adaptations_policy_version", table_name="meal_plan_adaptations")
    op.drop_index(
        "ix_meal_plan_adaptations_source_meal_plan_id",
        table_name="meal_plan_adaptations",
    )
    op.drop_index("ix_meal_plan_adaptations_meal_plan_id", table_name="meal_plan_adaptations")
    op.drop_table("meal_plan_adaptations")
