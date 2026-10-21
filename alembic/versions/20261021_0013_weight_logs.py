"""User weight history.

Revision ID: 20261021_0013
Revises: fcdf61504ece
"""
from alembic import op
import sqlalchemy as sa

revision = "20261021_0013"
down_revision = "fcdf61504ece"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("weight_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "log_date", name="uq_weight_logs_user_date"),
        sa.CheckConstraint("weight_kg >= 20 and weight_kg <= 500", name="ck_weight_logs_range"))


def downgrade():
    op.drop_table("weight_logs")
