"""Add membership tier to users

Revision ID: e50722d9e2fa
Revises: 99c18aa6fc56
Create Date: 2026-10-21 12:08:32.831367

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa



revision: str = 'e50722d9e2fa'
down_revision: str | Sequence[str] | None = '99c18aa6fc56'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "membership_tier",
            sa.Enum(
                "free",
                "premium",
                name="membershiptier",
                native_enum=False,
                length=32,
            ),
            server_default="free",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "users",
        "membership_tier",
    )