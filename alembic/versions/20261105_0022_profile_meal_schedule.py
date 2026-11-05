"""Profile sleep/wake schedules and saved local meal times.

Revision ID: 20261105_0022
Revises: 20261103_0021
"""
from alembic import op
import sqlalchemy as sa


revision = "20261105_0022"
down_revision = "20261103_0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_profiles", sa.Column("usual_wake_time", sa.Time(), nullable=True))
    op.add_column("user_profiles", sa.Column("usual_sleep_time", sa.Time(), nullable=True))
    op.add_column("user_profiles", sa.Column("timezone", sa.String(64), nullable=True))
    op.execute(sa.text(
        "UPDATE user_profiles SET usual_wake_time = TIME '07:00', "
        "usual_sleep_time = TIME '23:00', timezone = 'UTC', "
        "meals_per_day = LEAST(5, GREATEST(2, meals_per_day))"
    ))
    op.alter_column("user_profiles", "usual_wake_time", existing_type=sa.Time(), nullable=False)
    op.alter_column("user_profiles", "usual_sleep_time", existing_type=sa.Time(), nullable=False)
    op.alter_column("user_profiles", "timezone", existing_type=sa.String(64), nullable=False)
    op.create_check_constraint(
        "ck_user_profiles_meals_per_day_range", "user_profiles", "meals_per_day between 2 and 5"
    )
    op.create_check_constraint(
        "ck_user_profiles_wake_sleep_different", "user_profiles", "usual_wake_time <> usual_sleep_time"
    )
    op.add_column("meal_plan_items", sa.Column("scheduled_time", sa.Time(), nullable=True))


def downgrade():
    op.drop_column("meal_plan_items", "scheduled_time")
    op.drop_constraint("ck_user_profiles_wake_sleep_different", "user_profiles", type_="check")
    op.drop_constraint("ck_user_profiles_meals_per_day_range", "user_profiles", type_="check")
    op.drop_column("user_profiles", "timezone")
    op.drop_column("user_profiles", "usual_sleep_time")
    op.drop_column("user_profiles", "usual_wake_time")
