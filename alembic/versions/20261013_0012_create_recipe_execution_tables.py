"""create recipe execution tables

Revision ID: 20261013_0012
Revises: 20261010_0011
Create Date: 2026-10-13 00:12:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261013_0012"
down_revision: str | Sequence[str] | None = "20261010_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.add_column(
        "recipe_steps",
        sa.Column(
            "phase",
            sa.String(length=32),
            server_default="cook",
            nullable=False,
        ),
    )
    op.add_column("recipe_steps", sa.Column("timer_seconds", sa.Integer(), nullable=True))
    op.add_column("recipe_steps", sa.Column("cue_action", sa.String(length=64), nullable=True))
    op.add_column("recipe_steps", sa.Column("animation_key", sa.String(length=128), nullable=True))
    op.add_column("recipe_steps", sa.Column("media_asset_key", sa.String(length=128), nullable=True))
    op.add_column("recipe_steps", sa.Column("visual_cue", sa.String(length=128), nullable=True))
    op.create_check_constraint(
        "ck_recipe_steps_phase_valid",
        "recipe_steps",
        "phase in ('prep', 'cook', 'rest', 'assemble', 'serve')",
    )
    op.create_check_constraint(
        "ck_recipe_steps_timer_seconds_non_negative",
        "recipe_steps",
        "timer_seconds is null or timer_seconds >= 0",
    )

    op.create_table(
        "recipe_execution_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("recipe_id", sa.Uuid(), nullable=True),
        sa.Column("meal_plan_id", sa.Uuid(), nullable=True),
        sa.Column("meal_plan_item_id", sa.Uuid(), nullable=True),
        sa.Column("recipe_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("servings", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.Column("total_estimated_time_minutes", sa.Integer(), nullable=True),
        sa.Column("required_equipment_snapshot", sa.JSON(), nullable=False),
        sa.Column("ingredient_summary_snapshot", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status in ('not_started', 'in_progress', 'completed', 'abandoned')",
            name="ck_recipe_execution_sessions_status_valid",
        ),
        sa.CheckConstraint(
            "servings > 0",
            name="ck_recipe_execution_sessions_servings_positive",
        ),
        sa.CheckConstraint(
            "current_step_index >= 0",
            name="ck_recipe_execution_sessions_current_step_non_negative",
        ),
        sa.CheckConstraint(
            "total_estimated_time_minutes is null or total_estimated_time_minutes >= 0",
            name="ck_recipe_execution_sessions_total_time_non_negative",
        ),
        sa.ForeignKeyConstraint(["meal_plan_id"], ["meal_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["meal_plan_item_id"], ["meal_plan_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recipe_execution_sessions_user_id",
        "recipe_execution_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_recipe_execution_sessions_recipe_id",
        "recipe_execution_sessions",
        ["recipe_id"],
    )
    op.create_index(
        "ix_recipe_execution_sessions_meal_plan_id",
        "recipe_execution_sessions",
        ["meal_plan_id"],
    )
    op.create_index(
        "ix_recipe_execution_sessions_meal_plan_item_id",
        "recipe_execution_sessions",
        ["meal_plan_item_id"],
    )
    op.create_index(
        "ix_recipe_execution_sessions_status",
        "recipe_execution_sessions",
        ["status"],
    )
    op.create_index(
        "uq_recipe_execution_sessions_item_active",
        "recipe_execution_sessions",
        ["meal_plan_item_id"],
        unique=True,
        postgresql_where=sa.text(
            "meal_plan_item_id is not null and status in ('not_started', 'in_progress')"
        ),
    )

    op.create_table(
        "recipe_execution_step_snapshots",
        sa.Column("execution_session_id", sa.Uuid(), nullable=False),
        sa.Column("recipe_step_id", sa.Uuid(), nullable=True),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("recipe_step_position", sa.Integer(), nullable=False),
        sa.Column("instruction_snapshot", sa.Text(), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("timer_required", sa.Boolean(), nullable=False),
        sa.Column("timer_seconds", sa.Integer(), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("equipment_snapshot", sa.JSON(), nullable=False),
        sa.Column("ingredient_references_snapshot", sa.JSON(), nullable=False),
        sa.Column("cue_action", sa.String(length=64), nullable=True),
        sa.Column("animation_key", sa.String(length=128), nullable=True),
        sa.Column("media_asset_key", sa.String(length=128), nullable=True),
        sa.Column("visual_cue", sa.String(length=128), nullable=True),
        sa.Column("timer_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timer_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *timestamp_columns(),
        sa.CheckConstraint(
            "step_index >= 0",
            name="ck_recipe_execution_steps_index_non_negative",
        ),
        sa.CheckConstraint(
            "recipe_step_position > 0",
            name="ck_recipe_execution_steps_recipe_position_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(instruction_snapshot)) > 0",
            name="ck_recipe_execution_steps_instruction_not_blank",
        ),
        sa.CheckConstraint(
            "phase in ('prep', 'cook', 'rest', 'assemble', 'serve')",
            name="ck_recipe_execution_steps_phase_valid",
        ),
        sa.CheckConstraint(
            "duration_seconds is null or duration_seconds >= 0",
            name="ck_recipe_execution_steps_duration_non_negative",
        ),
        sa.CheckConstraint(
            "timer_seconds is null or timer_seconds >= 0",
            name="ck_recipe_execution_steps_timer_seconds_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["execution_session_id"],
            ["recipe_execution_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["recipe_step_id"], ["recipe_steps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "execution_session_id",
            "step_index",
            name="uq_recipe_execution_steps_session_index",
        ),
    )
    op.create_index(
        "ix_recipe_execution_steps_session_id",
        "recipe_execution_step_snapshots",
        ["execution_session_id"],
    )
    op.create_index(
        "ix_recipe_execution_steps_recipe_step_id",
        "recipe_execution_step_snapshots",
        ["recipe_step_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recipe_execution_steps_recipe_step_id",
        table_name="recipe_execution_step_snapshots",
    )
    op.drop_index(
        "ix_recipe_execution_steps_session_id",
        table_name="recipe_execution_step_snapshots",
    )
    op.drop_table("recipe_execution_step_snapshots")
    op.drop_index(
        "uq_recipe_execution_sessions_item_active",
        table_name="recipe_execution_sessions",
    )
    op.drop_index("ix_recipe_execution_sessions_status", table_name="recipe_execution_sessions")
    op.drop_index(
        "ix_recipe_execution_sessions_meal_plan_item_id",
        table_name="recipe_execution_sessions",
    )
    op.drop_index(
        "ix_recipe_execution_sessions_meal_plan_id",
        table_name="recipe_execution_sessions",
    )
    op.drop_index("ix_recipe_execution_sessions_recipe_id", table_name="recipe_execution_sessions")
    op.drop_index("ix_recipe_execution_sessions_user_id", table_name="recipe_execution_sessions")
    op.drop_table("recipe_execution_sessions")
    op.drop_constraint(
        "ck_recipe_steps_timer_seconds_non_negative",
        "recipe_steps",
        type_="check",
    )
    op.drop_constraint("ck_recipe_steps_phase_valid", "recipe_steps", type_="check")
    op.drop_column("recipe_steps", "visual_cue")
    op.drop_column("recipe_steps", "media_asset_key")
    op.drop_column("recipe_steps", "animation_key")
    op.drop_column("recipe_steps", "cue_action")
    op.drop_column("recipe_steps", "timer_seconds")
    op.drop_column("recipe_steps", "phase")
