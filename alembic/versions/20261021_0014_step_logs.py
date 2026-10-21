"""Manual daily steps.

Revision ID: 20261021_0014
Revises: 20261021_0013
"""
from alembic import op
import sqlalchemy as sa

revision = "20261021_0014"
down_revision = "20261021_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("step_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "log_date", name="uq_step_logs_user_date"),
        sa.CheckConstraint("steps >= 0 and steps <= 200000", name="ck_step_logs_range"))


def downgrade():
    op.drop_table("step_logs")
