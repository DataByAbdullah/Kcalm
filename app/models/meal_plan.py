from datetime import date
from uuid import UUID

from sqlalchemy import (
    Boolean,
    BigInteger,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import MealPlanStatus, WeeklyMealPlanStatus
from app.models.base import TimestampedUUIDBase


class WeeklyMealPlan(TimestampedUUIDBase):
    __tablename__ = "weekly_meal_plans"
    __table_args__ = (
        CheckConstraint(
            "status in ('generated', 'archived')",
            name="ck_weekly_meal_plans_status_valid",
        ),
        CheckConstraint(
            "end_date >= start_date",
            name="ck_weekly_meal_plans_end_after_start",
        ),
        Index("ix_weekly_meal_plans_user_id", "user_id"),
        Index("ix_weekly_meal_plans_start_date", "start_date"),
        Index("ix_weekly_meal_plans_end_date", "end_date"),
        Index("ix_weekly_meal_plans_status", "status"),
        Index(
            "uq_weekly_meal_plans_user_range_generated",
            "user_id",
            "start_date",
            "end_date",
            unique=True,
            postgresql_where=text("status = 'generated'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=WeeklyMealPlanStatus.GENERATED.value,
    )

    daily_plans = relationship(
        "MealPlan",
        back_populates="weekly_plan",
        order_by="MealPlan.plan_date",
    )


class MealPlan(TimestampedUUIDBase):
    __tablename__ = "meal_plans"
    __table_args__ = (
        CheckConstraint(
            "status in ('generated', 'archived')",
            name="ck_meal_plans_status_valid",
        ),
        CheckConstraint(
            "solver_status in ('optimal', 'feasible')",
            name="ck_meal_plans_solver_status_valid",
        ),
        CheckConstraint("calorie_target > 0", name="ck_meal_plans_calorie_target_positive"),
        CheckConstraint("protein_target > 0", name="ck_meal_plans_protein_target_positive"),
        CheckConstraint(
            "carbohydrate_target > 0",
            name="ck_meal_plans_carbohydrate_target_positive",
        ),
        CheckConstraint("fat_target > 0", name="ck_meal_plans_fat_target_positive"),
        CheckConstraint("candidate_count >= 0", name="ck_meal_plans_candidate_count_non_negative"),
        CheckConstraint(
            "solve_time_seconds >= 0",
            name="ck_meal_plans_solve_time_non_negative",
        ),
        Index("ix_meal_plans_user_id", "user_id"),
        Index("ix_meal_plans_weekly_plan_id", "weekly_plan_id"),
        Index("ix_meal_plans_plan_date", "plan_date"),
        Index("ix_meal_plans_status", "status"),
        Index(
            "uq_meal_plans_user_id_plan_date_generated",
            "user_id",
            "plan_date",
            unique=True,
            postgresql_where=text("status = 'generated'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    weekly_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("weekly_meal_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MealPlanStatus.GENERATED.value,
    )
    solver_status: Mapped[str] = mapped_column(String(32), nullable=False)
    calorie_target: Mapped[float] = mapped_column(Float, nullable=False)
    protein_target: Mapped[float] = mapped_column(Float, nullable=False)
    carbohydrate_target: Mapped[float] = mapped_column(Float, nullable=False)
    fat_target: Mapped[float] = mapped_column(Float, nullable=False)
    within_preferred_tolerance: Mapped[bool] = mapped_column(Boolean, nullable=False)
    objective_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    solve_time_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)

    weekly_plan = relationship("WeeklyMealPlan", back_populates="daily_plans")
    items = relationship(
        "MealPlanItem",
        back_populates="meal_plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MealPlanItem.position",
    )
    micronutrient_targets = relationship(
        "MealPlanMicronutrientTargetSnapshot",
        back_populates="meal_plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MealPlanMicronutrientTargetSnapshot.nutrient_code",
    )


class MealPlanItem(TimestampedUUIDBase):
    __tablename__ = "meal_plan_items"
    __table_args__ = (
        CheckConstraint(
            "meal_type in ('breakfast', 'lunch', 'dinner', 'snack')",
            name="ck_meal_plan_items_meal_type_valid",
        ),
        CheckConstraint("servings > 0", name="ck_meal_plan_items_servings_positive"),
        CheckConstraint("position > 0", name="ck_meal_plan_items_position_positive"),
        CheckConstraint(
            "length(btrim(recipe_name_snapshot)) > 0",
            name="ck_meal_plan_items_recipe_name_not_blank",
        ),
        UniqueConstraint("meal_plan_id", "position", name="uq_meal_plan_items_plan_position"),
        Index("ix_meal_plan_items_meal_plan_id", "meal_plan_id"),
        Index("ix_meal_plan_items_recipe_id", "recipe_id"),
    )

    meal_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("meal_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    meal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    recipe_id: Mapped[UUID] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    recipe_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    servings: Mapped[float] = mapped_column(Float, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    meal_plan = relationship("MealPlan", back_populates="items")
    nutrients = relationship(
        "MealPlanItemNutrientSnapshot",
        back_populates="meal_plan_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MealPlanItemNutrientSnapshot.nutrient_code",
    )
    ingredient_snapshots = relationship(
        "MealPlanItemIngredientSnapshot",
        back_populates="meal_plan_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MealPlanItemIngredientSnapshot.food_name_snapshot",
    )
    logs = relationship(
        "MealLog",
        back_populates="meal_plan_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MealLog.created_at",
    )


class MealPlanItemNutrientSnapshot(TimestampedUUIDBase):
    __tablename__ = "meal_plan_item_nutrients"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_meal_plan_item_nutrients_amount_non_negative"),
        CheckConstraint(
            "length(btrim(nutrient_code)) > 0",
            name="ck_meal_plan_item_nutrients_code_not_blank",
        ),
        CheckConstraint(
            "length(btrim(nutrient_name)) > 0",
            name="ck_meal_plan_item_nutrients_name_not_blank",
        ),
        CheckConstraint(
            "length(btrim(unit)) > 0",
            name="ck_meal_plan_item_nutrients_unit_not_blank",
        ),
        UniqueConstraint(
            "meal_plan_item_id",
            "nutrient_code",
            name="uq_meal_plan_item_nutrients_item_code",
        ),
        Index("ix_meal_plan_item_nutrients_item_id", "meal_plan_item_id"),
        Index("ix_meal_plan_item_nutrients_nutrient_code", "nutrient_code"),
    )

    meal_plan_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("meal_plan_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    nutrient_code: Mapped[str] = mapped_column(String(64), nullable=False)
    nutrient_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)

    meal_plan_item = relationship("MealPlanItem", back_populates="nutrients")


class MealPlanItemIngredientSnapshot(TimestampedUUIDBase):
    __tablename__ = "meal_plan_item_ingredients"
    __table_args__ = (
        CheckConstraint(
            "quantity_grams > 0",
            name="ck_meal_plan_item_ingredients_quantity_positive",
        ),
        CheckConstraint(
            "length(btrim(food_name_snapshot)) > 0",
            name="ck_meal_plan_item_ingredients_food_name_not_blank",
        ),
        UniqueConstraint(
            "meal_plan_item_id",
            "food_id",
            name="uq_meal_plan_item_ingredients_item_food",
        ),
        Index("ix_meal_plan_item_ingredients_item_id", "meal_plan_item_id"),
        Index("ix_meal_plan_item_ingredients_food_id", "food_id"),
    )

    meal_plan_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("meal_plan_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    food_id: Mapped[UUID] = mapped_column(ForeignKey("foods.id"), nullable=False)
    food_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity_grams: Mapped[float] = mapped_column(Float, nullable=False)

    meal_plan_item = relationship("MealPlanItem", back_populates="ingredient_snapshots")
    food = relationship("Food")


class MealPlanMicronutrientTargetSnapshot(TimestampedUUIDBase):
    __tablename__ = "meal_plan_micronutrient_targets"
    __table_args__ = (
        CheckConstraint("target > 0", name="ck_meal_plan_micro_targets_target_positive"),
        CheckConstraint(
            "minimum_target is null or minimum_target > 0",
            name="ck_meal_plan_micro_targets_minimum_positive",
        ),
        CheckConstraint(
            "upper_limit is null or upper_limit > 0",
            name="ck_meal_plan_micro_targets_upper_positive",
        ),
        CheckConstraint(
            "length(btrim(nutrient_code)) > 0",
            name="ck_meal_plan_micro_targets_code_not_blank",
        ),
        CheckConstraint(
            "length(btrim(nutrient_name)) > 0",
            name="ck_meal_plan_micro_targets_name_not_blank",
        ),
        CheckConstraint(
            "length(btrim(unit)) > 0",
            name="ck_meal_plan_micro_targets_unit_not_blank",
        ),
        UniqueConstraint(
            "meal_plan_id",
            "nutrient_code",
            name="uq_meal_plan_micro_targets_plan_code",
        ),
        Index("ix_meal_plan_micro_targets_meal_plan_id", "meal_plan_id"),
        Index("ix_meal_plan_micro_targets_nutrient_code", "nutrient_code"),
    )

    meal_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("meal_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    nutrient_code: Mapped[str] = mapped_column(String(64), nullable=False)
    nutrient_name: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    minimum_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_limit_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    meal_plan = relationship("MealPlan", back_populates="micronutrient_targets")
