"""Daily habits and completion history."""
from alembic import op
import sqlalchemy as sa

revision = "20261021_0015"
down_revision = "20261021_0014"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade():
    op.create_table("habits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False), *timestamps(),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_habits_name"))
    op.create_index("ix_habits_user_id", "habits", ["user_id"])
    op.create_table("habit_completions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("habit_id", sa.Uuid(), sa.ForeignKey("habits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("log_date", sa.Date(), nullable=False), *timestamps(),
        sa.UniqueConstraint("habit_id", "log_date", name="uq_habit_completions_habit_date"))


def downgrade():
    op.drop_table("habit_completions")
    op.drop_table("habits")
