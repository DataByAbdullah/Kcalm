"""User-owned daily water, fruit/vegetable, and sleep entries.

Revision ID: 20261028_0020
Revises: 20261026_0019
"""
from alembic import op
import sqlalchemy as sa

revision = "20261028_0020"
down_revision = "20261026_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("daily_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("water_glasses", sa.Integer(), nullable=False),
        sa.Column("fruit_veg_servings", sa.Float(), nullable=False),
        sa.Column("sleep_hours", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "log_date", name="uq_daily_metrics_user_date"),
        sa.CheckConstraint("water_glasses >= 0 and water_glasses <= 100", name="ck_daily_metrics_water_range"),
        sa.CheckConstraint("fruit_veg_servings >= 0 and fruit_veg_servings <= 100", name="ck_daily_metrics_servings_range"),
        sa.CheckConstraint("sleep_hours >= 0 and sleep_hours <= 24", name="ck_daily_metrics_sleep_range"))


def downgrade():
    op.drop_table("daily_metrics")
