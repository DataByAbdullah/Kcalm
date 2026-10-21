"""Add target weight to user profiles

Revision ID: fcdf61504ece
Revises: e50722d9e2fa
Create Date: 2026-10-21 12:23:53.961108

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa



revision: str = 'fcdf61504ece'
down_revision: str | Sequence[str] | None = 'e50722d9e2fa'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column(
            "target_weight_kg",
            sa.Float(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "user_profiles",
        "target_weight_kg",
    )