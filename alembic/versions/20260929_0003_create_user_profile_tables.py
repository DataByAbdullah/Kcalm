"""create user profile tables

Revision ID: 20260929_0003
Revises: 20260929_0002
Create Date: 2026-09-29 00:20:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260929_0003"
down_revision: str | Sequence[str] | None = "20260929_0002"
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


def user_scoped_table(table_name: str, value_column: sa.Column, unique_name: str) -> None:
    op.create_table(
        table_name,
        value_column,
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", value_column.name, name=unique_name),
    )
    op.create_index(op.f(f"ix_{table_name}_user_id"), table_name, ["user_id"], unique=False)


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("sex", sa.String(length=16), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("activity_level", sa.String(length=32), nullable=False),
        sa.Column("goal", sa.String(length=32), nullable=False),
        sa.Column("target_rate", sa.Float(), nullable=True),
        sa.Column("max_cooking_minutes", sa.Integer(), nullable=False),
        sa.Column("meals_per_day", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_user_profiles_user_id"), "user_profiles", ["user_id"], unique=False)

    user_scoped_table(
        "user_allergies",
        sa.Column("name", sa.String(length=128), nullable=False),
        "uq_user_allergies_user_id_name",
    )
    user_scoped_table(
        "user_dietary_restrictions",
        sa.Column("name", sa.String(length=128), nullable=False),
        "uq_user_dietary_restrictions_user_id_name",
    )
    user_scoped_table(
        "user_preferred_foods",
        sa.Column("name", sa.String(length=128), nullable=False),
        "uq_user_preferred_foods_user_id_name",
    )
    user_scoped_table(
        "user_disliked_foods",
        sa.Column("name", sa.String(length=128), nullable=False),
        "uq_user_disliked_foods_user_id_name",
    )
    user_scoped_table(
        "user_equipment",
        sa.Column("equipment", sa.String(length=128), nullable=False),
        "uq_user_equipment_user_id_equipment",
    )


def downgrade() -> None:
    for table_name in (
        "user_equipment",
        "user_disliked_foods",
        "user_preferred_foods",
        "user_dietary_restrictions",
        "user_allergies",
    ):
        op.drop_index(op.f(f"ix_{table_name}_user_id"), table_name=table_name)
        op.drop_table(table_name)

    op.drop_index(op.f("ix_user_profiles_user_id"), table_name="user_profiles")
    op.drop_table("user_profiles")
