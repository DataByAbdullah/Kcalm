"""Add extra food logs

Revision ID: 81602cb15cbe
Revises: 93c0834244f8
Create Date: 2026-10-20 18:40:13.369048

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa



revision: str = '81602cb15cbe'
down_revision: str | Sequence[str] | None = '93c0834244f8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extra_food_logs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("food_id", sa.Uuid(), nullable=True),
        sa.Column("quantity_grams", sa.Float(), nullable=True),
        sa.Column("calories", sa.Float(), nullable=False),
        sa.Column("protein_g", sa.Float(), nullable=False),
        sa.Column("carbs_g", sa.Float(), nullable=False),
        sa.Column("fat_g", sa.Float(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["food_id"], ["foods.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_extra_food_logs_log_date",
        "extra_food_logs",
        ["log_date"],
        unique=False,
    )

    op.create_index(
        "ix_extra_food_logs_user_id",
        "extra_food_logs",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extra_food_logs_user_id",
        table_name="extra_food_logs",
    )

    op.drop_index(
        "ix_extra_food_logs_log_date",
        table_name="extra_food_logs",
    )

    op.drop_table("extra_food_logs")