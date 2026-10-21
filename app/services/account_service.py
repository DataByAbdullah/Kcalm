from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import APIErrorException
from app.models.user import User
from app.core.database import Base
from app.schemas.account import UserDataExportResponse
from app.schemas.auth import UserResponse


# Explicit allowlist keeps newly added private/security tables out of exports.
EXPORT_ROOTS = (
    "user_profiles", "user_allergies", "user_dietary_restrictions", "user_preferred_foods",
    "user_disliked_foods", "user_equipment", "weight_logs", "step_logs", "habits",
    "notifications", "meal_plans", "weekly_meal_plans", "grocery_lists", "meal_logs",
    "extra_food_logs", "recipe_execution_sessions",
)
EXPORT_CHILDREN = (
    ("habit_completions", "habit_id", "habits"),
    ("meal_plan_items", "meal_plan_id", "meal_plans"),
    ("meal_plan_micronutrient_targets", "meal_plan_id", "meal_plans"),
    ("meal_plan_item_nutrients", "meal_plan_item_id", "meal_plan_items"),
    ("meal_plan_item_ingredients", "meal_plan_item_id", "meal_plan_items"),
    ("meal_plan_adaptations", "meal_plan_id", "meal_plans"),
    ("grocery_list_items", "grocery_list_id", "grocery_lists"),
    ("meal_log_nutrients", "meal_log_id", "meal_logs"),
    ("extra_food_log_nutrients", "extra_food_log_id", "extra_food_logs"),
    ("recipe_execution_step_snapshots", "execution_session_id", "recipe_execution_sessions"),
)


def export_user_data(db, user):
    tables = Base.metadata.tables
    conditions = {name: tables[name].c.user_id == user.id for name in EXPORT_ROOTS}
    for name, column, parent in EXPORT_CHILDREN:
        conditions[name] = tables[name].c[column].in_(select(tables[parent].c.id).where(conditions[parent]))
    records = {name: [dict(row) for row in db.execute(select(tables[name]).where(condition)
               .order_by(tables[name].c.created_at, tables[name].c.id)).mappings()]
               for name, condition in conditions.items()}
    return UserDataExportResponse(exported_at=datetime.now(timezone.utc),
                                   user=UserResponse.model_validate(user), records=records)


def delete_account(db, user):
    try:
        # Database cascades cover owned records that have no User ORM relationship.
        db.execute(delete(User).where(User.id == user.id))
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise APIErrorException(500, "ACCOUNT_DELETE_FAILED", "Account could not be deleted.") from exc
