from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, Float, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import MealLogStatus, MealLogType
from app.models.base import TimestampedUUIDBase


class MealLog(TimestampedUUIDBase):
    __tablename__ = "meal_logs"
    __table_args__ = (
        CheckConstraint(
            "log_type in ('ate_as_planned', 'corrected')",
            name="ck_meal_logs_log_type_valid",
        ),
        CheckConstraint("status in ('active')", name="ck_meal_logs_status_valid"),
        CheckConstraint(
            "source_type is null or source_type in ('food', 'recipe')",
            name="ck_meal_logs_source_type_valid",
        ),
        CheckConstraint(
            "quantity_grams is null or quantity_grams > 0",
            name="ck_meal_logs_quantity_grams_positive",
        ),
        CheckConstraint(
            "servings is null or servings > 0",
            name="ck_meal_logs_servings_positive",
        ),
        CheckConstraint(
            """
            (log_type = 'ate_as_planned'
                and source_type is null
                and food_id is null
                and recipe_id is null
                and quantity_grams is null
                and servings is null)
            or
            (log_type = 'corrected'
                and source_type = 'food'
                and food_id is not null
                and recipe_id is null
                and quantity_grams is not null
                and servings is null)
            or
            (log_type = 'corrected'
                and source_type = 'recipe'
                and recipe_id is not null
                and food_id is null
                and servings is not null
                and quantity_grams is null)
            """,
            name="ck_meal_logs_type_source_consistent",
        ),
        Index("ix_meal_logs_user_id", "user_id"),
        Index("ix_meal_logs_meal_plan_id", "meal_plan_id"),
        Index("ix_meal_logs_meal_plan_item_id", "meal_plan_item_id"),
        Index("ix_meal_logs_log_date", "log_date"),
        Index("ix_meal_logs_status", "status"),
        Index(
            "uq_meal_logs_meal_plan_item_id_active",
            "meal_plan_item_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    meal_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("meal_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    meal_plan_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("meal_plan_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    log_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MealLogType.ATE_AS_PLANNED.value,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=MealLogStatus.ACTIVE.value,
    )
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    food_id: Mapped[UUID | None] = mapped_column(ForeignKey("foods.id"), nullable=True)
    recipe_id: Mapped[UUID | None] = mapped_column(ForeignKey("recipes.id"), nullable=True)
    quantity_grams: Mapped[float | None] = mapped_column(Float, nullable=True)
    servings: Mapped[float | None] = mapped_column(Float, nullable=True)
    nutrient_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user = relationship("User")
    meal_plan = relationship("MealPlan")
    meal_plan_item = relationship("MealPlanItem", back_populates="logs")
    food = relationship("Food")
    recipe = relationship("Recipe")
    nutrients = relationship(
        "MealLogNutrientSnapshot",
        back_populates="meal_log",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MealLogNutrientSnapshot.nutrient_code",
    )


class MealLogNutrientSnapshot(TimestampedUUIDBase):
    __tablename__ = "meal_log_nutrients"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_meal_log_nutrients_amount_non_negative"),
        CheckConstraint(
            "length(btrim(nutrient_code)) > 0",
            name="ck_meal_log_nutrients_code_not_blank",
        ),
        CheckConstraint(
            "length(btrim(nutrient_name)) > 0",
            name="ck_meal_log_nutrients_name_not_blank",
        ),
        CheckConstraint(
            "length(btrim(unit)) > 0",
            name="ck_meal_log_nutrients_unit_not_blank",
        ),
        Index("ix_meal_log_nutrients_meal_log_id", "meal_log_id"),
        Index("ix_meal_log_nutrients_nutrient_code", "nutrient_code"),
        Index(
            "uq_meal_log_nutrients_log_code",
            "meal_log_id",
            "nutrient_code",
            unique=True,
        ),
    )

    meal_log_id: Mapped[UUID] = mapped_column(
        ForeignKey("meal_logs.id", ondelete="CASCADE"),
        nullable=False,
    )
    nutrient_code: Mapped[str] = mapped_column(String(64), nullable=False)
    nutrient_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)

    meal_log = relationship("MealLog", back_populates="nutrients")
