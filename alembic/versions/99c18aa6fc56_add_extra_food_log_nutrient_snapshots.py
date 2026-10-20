"""Add extra food log nutrient snapshots

Revision ID: 99c18aa6fc56
Revises: 81602cb15cbe
Create Date: 2026-10-20 19:07:12.845595

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa



revision: str = '99c18aa6fc56'
down_revision: str | Sequence[str] | None = '81602cb15cbe'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "extra_food_log_nutrients",
        sa.Column("extra_food_log_id", sa.Uuid(), nullable=False),
        sa.Column("nutrient_code", sa.String(length=64), nullable=False),
        sa.Column("nutrient_name", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_extra_food_log_nutrients_amount_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["extra_food_log_id"],
            ["extra_food_logs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "extra_food_log_id",
            "nutrient_code",
            name="uq_extra_food_log_nutrients_log_code",
        ),
    )

    op.create_index(
        "ix_extra_food_log_nutrients_extra_food_log_id",
        "extra_food_log_nutrients",
        ["extra_food_log_id"],
        unique=False,
    )

    op.create_index(
        "ix_extra_food_log_nutrients_nutrient_code",
        "extra_food_log_nutrients",
        ["nutrient_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extra_food_log_nutrients_nutrient_code",
        table_name="extra_food_log_nutrients",
    )

    op.drop_index(
        "ix_extra_food_log_nutrients_extra_food_log_id",
        table_name="extra_food_log_nutrients",
    )

    op.drop_table("extra_food_log_nutrients")