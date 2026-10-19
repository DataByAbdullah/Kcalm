from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import TimestampedUUIDBase


class MealPlanAdaptationSnapshot(TimestampedUUIDBase):
    __tablename__ = "meal_plan_adaptations"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(policy_version)) > 0",
            name="ck_meal_plan_adaptations_policy_version_not_blank",
        ),
        CheckConstraint(
            "base_calorie_target > 0",
            name="ck_meal_plan_adaptations_base_calorie_positive",
        ),
        CheckConstraint(
            "adjusted_calorie_target > 0",
            name="ck_meal_plan_adaptations_adjusted_calorie_positive",
        ),
        CheckConstraint(
            "compensation_fraction >= 0 and compensation_fraction <= 1",
            name="ck_meal_plan_adaptations_fraction_range",
        ),
        CheckConstraint(
            "base_protein_target > 0",
            name="ck_meal_plan_adaptations_base_protein_positive",
        ),
        CheckConstraint(
            "base_carbohydrate_target >= 0",
            name="ck_meal_plan_adaptations_base_carbs_non_negative",
        ),
        CheckConstraint(
            "base_fat_target > 0",
            name="ck_meal_plan_adaptations_base_fat_positive",
        ),
        CheckConstraint(
            "adjusted_protein_target > 0",
            name="ck_meal_plan_adaptations_adjusted_protein_positive",
        ),
        CheckConstraint(
            "adjusted_carbohydrate_target >= 0",
            name="ck_meal_plan_adaptations_adjusted_carbs_non_negative",
        ),
        CheckConstraint(
            "adjusted_fat_target > 0",
            name="ck_meal_plan_adaptations_adjusted_fat_positive",
        ),
        Index("ix_meal_plan_adaptations_meal_plan_id", "meal_plan_id", unique=True),
        Index("ix_meal_plan_adaptations_source_meal_plan_id", "source_meal_plan_id"),
        Index("ix_meal_plan_adaptations_policy_version", "policy_version"),
    )

    meal_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("meal_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_meal_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("meal_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    base_calorie_target: Mapped[float] = mapped_column(Float, nullable=False)
    source_actual_calories: Mapped[float] = mapped_column(Float, nullable=False)
    source_calorie_deviation: Mapped[float] = mapped_column(Float, nullable=False)
    compensation_fraction: Mapped[float] = mapped_column(Float, nullable=False)
    compensation_amount: Mapped[float] = mapped_column(Float, nullable=False)
    adjusted_calorie_target: Mapped[float] = mapped_column(Float, nullable=False)
    base_protein_target: Mapped[float] = mapped_column(Float, nullable=False)
    base_carbohydrate_target: Mapped[float] = mapped_column(Float, nullable=False)
    base_fat_target: Mapped[float] = mapped_column(Float, nullable=False)
    adjusted_protein_target: Mapped[float] = mapped_column(Float, nullable=False)
    adjusted_carbohydrate_target: Mapped[float] = mapped_column(Float, nullable=False)
    adjusted_fat_target: Mapped[float] = mapped_column(Float, nullable=False)
    safety_cap_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    meal_plan = relationship("MealPlan", foreign_keys=[meal_plan_id])
    source_meal_plan = relationship("MealPlan", foreign_keys=[source_meal_plan_id])
