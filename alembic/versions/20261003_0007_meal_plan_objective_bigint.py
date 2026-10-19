"""make meal plan objective value bigint

Revision ID: 20261003_0007
Revises: 20261003_0006
Create Date: 2026-10-03 00:07:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261003_0007"
down_revision: str | Sequence[str] | None = "20261003_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "meal_plans",
        "objective_value",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "meal_plans",
        "objective_value",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
    )
