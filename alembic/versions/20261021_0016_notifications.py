"""Owned notification inbox."""
from alembic import op
import sqlalchemy as sa

revision = "20261021_0016"
down_revision = "20261021_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_key", sa.String(150), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.String(1000), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "event_key", name="uq_notifications_user_event"))
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])


def downgrade():
    op.drop_table("notifications")
