"""Administrator authorization and shared rate-limit buckets.

Revision ID: 20261103_0021
Revises: 20261028_0020
"""
from alembic import op
import sqlalchemy as sa


revision = "20261103_0021"
down_revision = "20261028_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "rate_limit_buckets",
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("request_count > 0", name="ck_rate_limit_buckets_count_positive"),
    )
    op.create_index("ix_rate_limit_buckets_expires_at", "rate_limit_buckets", ["expires_at"])


def downgrade():
    op.drop_index("ix_rate_limit_buckets_expires_at", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
    op.drop_column("users", "is_admin")
