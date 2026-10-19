from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import GroceryCategory, GroceryListStatus
from app.models.base import TimestampedUUIDBase


class GroceryList(TimestampedUUIDBase):
    __tablename__ = "grocery_lists"
    __table_args__ = (
        CheckConstraint(
            "status in ('active', 'archived')",
            name="ck_grocery_lists_status_valid",
        ),
        Index("ix_grocery_lists_user_id", "user_id"),
        Index("ix_grocery_lists_weekly_plan_id", "weekly_plan_id"),
        Index("ix_grocery_lists_status", "status"),
        Index(
            "uq_grocery_lists_weekly_plan_id_active",
            "weekly_plan_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    weekly_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("weekly_meal_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=GroceryListStatus.ACTIVE.value,
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    weekly_plan = relationship("WeeklyMealPlan")
    items = relationship(
        "GroceryListItem",
        back_populates="grocery_list",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GroceryListItem.category, GroceryListItem.food_name_snapshot, GroceryListItem.id",
    )


class GroceryListItem(TimestampedUUIDBase):
    __tablename__ = "grocery_list_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_grocery_list_items_quantity_positive"),
        CheckConstraint(
            "quantity_grams is null or quantity_grams > 0",
            name="ck_grocery_list_items_quantity_grams_positive",
        ),
        CheckConstraint(
            "length(btrim(food_name_snapshot)) > 0",
            name="ck_grocery_list_items_food_name_not_blank",
        ),
        CheckConstraint("length(btrim(unit)) > 0", name="ck_grocery_list_items_unit_not_blank"),
        CheckConstraint(
            "category in ('produce', 'meat_seafood', 'dairy', 'grains', 'pantry', 'frozen', 'other')",
            name="ck_grocery_list_items_category_valid",
        ),
        Index("ix_grocery_list_items_grocery_list_id", "grocery_list_id"),
        Index("ix_grocery_list_items_food_id", "food_id"),
        Index("ix_grocery_list_items_category", "category"),
        Index("ix_grocery_list_items_checked", "checked"),
        Index(
            "uq_grocery_list_items_list_food_generated",
            "grocery_list_id",
            "food_id",
            unique=True,
            postgresql_where=text("food_id is not null and manually_added = false"),
        ),
    )

    grocery_list_id: Mapped[UUID] = mapped_column(
        ForeignKey("grocery_lists.id", ondelete="CASCADE"),
        nullable=False,
    )
    food_id: Mapped[UUID | None] = mapped_column(ForeignKey("foods.id"), nullable=True)
    food_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity_grams: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=GroceryCategory.OTHER.value,
    )
    checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manually_added: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    grocery_list = relationship("GroceryList", back_populates="items")
    food = relationship("Food")
