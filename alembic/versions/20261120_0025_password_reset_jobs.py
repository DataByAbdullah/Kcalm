"""Durable password-reset dispatch, without plaintext recipients or reset tokens.

Revision ID: 20261120_0025
Revises: 20261118_0024
"""
from alembic import op
import sqlalchemy as sa

revision = "20261120_0025"
down_revision = "20261118_0024"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "password_reset_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("password_fingerprint", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_category", sa.String(40), nullable=True),
        sa.CheckConstraint("status IN ('pending','processing','accepted','discarded','failed')", name="ck_reset_jobs_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_reset_jobs_attempts"),
        sa.CheckConstraint("(user_id IS NULL) = (password_fingerprint IS NULL)", name="ck_reset_jobs_subject"),
        sa.CheckConstraint("(status = 'processing' AND lease_id IS NOT NULL AND lease_until IS NOT NULL) OR "
                           "(status <> 'processing' AND lease_id IS NULL AND lease_until IS NULL)", name="ck_reset_jobs_lease"),
    )
    op.create_index("ix_reset_jobs_available", "password_reset_jobs", ["status", "available_at"])
    op.create_index("ix_reset_jobs_lease", "password_reset_jobs", ["lease_until"])
    op.create_index("ix_reset_jobs_user", "password_reset_jobs", ["user_id"])
    op.create_index("ix_reset_jobs_cleanup", "password_reset_jobs", ["status", "updated_at"])


def downgrade():
    # Drain/stop dispatchers before a deliberate feature rollback.
    op.drop_table("password_reset_jobs")
