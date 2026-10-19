from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import RecipeExecutionStatus, RecipeStepPhase
from app.models.base import TimestampedUUIDBase


class RecipeExecutionSession(TimestampedUUIDBase):
    __tablename__ = "recipe_execution_sessions"
    __table_args__ = (
        CheckConstraint(
            "status in ('not_started', 'in_progress', 'completed', 'abandoned')",
            name="ck_recipe_execution_sessions_status_valid",
        ),
        CheckConstraint("servings > 0", name="ck_recipe_execution_sessions_servings_positive"),
        CheckConstraint(
            "current_step_index >= 0",
            name="ck_recipe_execution_sessions_current_step_non_negative",
        ),
        CheckConstraint(
            "total_estimated_time_minutes is null or total_estimated_time_minutes >= 0",
            name="ck_recipe_execution_sessions_total_time_non_negative",
        ),
        Index("ix_recipe_execution_sessions_user_id", "user_id"),
        Index("ix_recipe_execution_sessions_recipe_id", "recipe_id"),
        Index("ix_recipe_execution_sessions_meal_plan_id", "meal_plan_id"),
        Index("ix_recipe_execution_sessions_meal_plan_item_id", "meal_plan_item_id"),
        Index("ix_recipe_execution_sessions_status", "status"),
        Index(
            "uq_recipe_execution_sessions_item_active",
            "meal_plan_item_id",
            unique=True,
            postgresql_where=text(
                "meal_plan_item_id is not null and status in ('not_started', 'in_progress')"
            ),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipe_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"),
        nullable=True,
    )
    meal_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("meal_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    meal_plan_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("meal_plan_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    recipe_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    servings: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RecipeExecutionStatus.IN_PROGRESS.value,
    )
    current_step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_estimated_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    required_equipment_snapshot: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ingredient_summary_snapshot: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    recipe = relationship("Recipe")
    meal_plan = relationship("MealPlan")
    meal_plan_item = relationship("MealPlanItem")
    step_snapshots = relationship(
        "RecipeExecutionStepSnapshot",
        back_populates="execution_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecipeExecutionStepSnapshot.step_index",
    )


class RecipeExecutionStepSnapshot(TimestampedUUIDBase):
    __tablename__ = "recipe_execution_step_snapshots"
    __table_args__ = (
        CheckConstraint("step_index >= 0", name="ck_recipe_execution_steps_index_non_negative"),
        CheckConstraint(
            "recipe_step_position > 0",
            name="ck_recipe_execution_steps_recipe_position_positive",
        ),
        CheckConstraint(
            "length(btrim(instruction_snapshot)) > 0",
            name="ck_recipe_execution_steps_instruction_not_blank",
        ),
        CheckConstraint(
            "phase in ('prep', 'cook', 'rest', 'assemble', 'serve')",
            name="ck_recipe_execution_steps_phase_valid",
        ),
        CheckConstraint(
            "duration_seconds is null or duration_seconds >= 0",
            name="ck_recipe_execution_steps_duration_non_negative",
        ),
        CheckConstraint(
            "timer_seconds is null or timer_seconds >= 0",
            name="ck_recipe_execution_steps_timer_seconds_non_negative",
        ),
        UniqueConstraint(
            "execution_session_id",
            "step_index",
            name="uq_recipe_execution_steps_session_index",
        ),
        Index("ix_recipe_execution_steps_session_id", "execution_session_id"),
        Index("ix_recipe_execution_steps_recipe_step_id", "recipe_step_id"),
    )

    execution_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("recipe_execution_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipe_step_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("recipe_steps.id", ondelete="SET NULL"),
        nullable=True,
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    recipe_step_position: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RecipeStepPhase.COOK.value,
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timer_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timer_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    equipment_snapshot: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ingredient_references_snapshot: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    cue_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    animation_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    media_asset_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    visual_cue: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timer_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timer_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    execution_session = relationship(
        "RecipeExecutionSession",
        back_populates="step_snapshots",
    )
    recipe_step = relationship("RecipeStep")
