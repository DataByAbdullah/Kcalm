"""Add full name to users

Revision ID: 93c0834244f8
Revises: 20261013_0012
Create Date: 2026-10-20 17:35:17.332958

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa



revision: str = '93c0834244f8'
down_revision: str | Sequence[str] | None = '20261013_0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("full_name", sa.String(length=150), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "full_name")


