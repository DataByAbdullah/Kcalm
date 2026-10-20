from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import APIErrorException
from app.meal_planning.scaling import scale_amount, unscale_amount
from app.models.extra_food_log import ExtraFoodLog
from app.models.user import User
from app.schemas.extra_food_log import ExtraFoodLogCreateRequest
from app.services.food_service import get_food_detail


REQUIRED_MACRO_CODES = (
    "calories",
    "protein",
    "carbohydrates",
    "fat",
)


def extra_food_log_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="EXTRA_FOOD_LOG_NOT_FOUND",
        message="Extra food log not found.",
    )


def food_macros_incomplete_error() -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="FOOD_MACROS_INCOMPLETE",
        message="Food does not contain all required macro nutrients.",
    )


def extra_food_log_save_failed_error() -> APIErrorException:
    return APIErrorException(
        status_code=500,
        code="EXTRA_FOOD_LOG_SAVE_FAILED",
        message="Extra food log could not be saved.",
    )


def create_extra_food_log(
    db: Session,
    user: User,
    payload: ExtraFoodLogCreateRequest,
) -> ExtraFoodLog:
    if payload.food_id is not None:
        food = get_food_detail(
            db=db,
            food_id=payload.food_id,
        )

        nutrient_map = {
            nutrient.nutrient_code: nutrient.amount
            for nutrient in food.nutrients
        }

        if any(
            code not in nutrient_map
            for code in REQUIRED_MACRO_CODES
        ):
            raise food_macros_incomplete_error()

        quantity_grams = payload.quantity_grams
        if quantity_grams is None:
            raise extra_food_log_save_failed_error()

        def amount_for(code: str) -> float:
            amount = nutrient_map[code] * quantity_grams / 100
            return unscale_amount(scale_amount(amount))

        extra_log = ExtraFoodLog(
            user_id=user.id,
            log_date=payload.log_date,
            name=food.name,
            food_id=food.id,
            quantity_grams=quantity_grams,
            calories=amount_for("calories"),
            protein_g=amount_for("protein"),
            carbs_g=amount_for("carbohydrates"),
            fat_g=amount_for("fat"),
        )

    else:
        extra_log = ExtraFoodLog(
            user_id=user.id,
            log_date=payload.log_date,
            name=payload.name.strip() if payload.name else "",
            food_id=None,
            quantity_grams=None,
            calories=payload.calories if payload.calories is not None else 0.0,
            protein_g=payload.protein_g if payload.protein_g is not None else 0.0,
            carbs_g=payload.carbs_g if payload.carbs_g is not None else 0.0,
            fat_g=payload.fat_g if payload.fat_g is not None else 0.0,
        )

    try:
        db.add(extra_log)
        db.commit()
        db.refresh(extra_log)
    except SQLAlchemyError as exc:
        db.rollback()
        raise extra_food_log_save_failed_error() from exc

    return extra_log


def delete_extra_food_log(
    db: Session,
    user: User,
    extra_food_log_id: UUID,
) -> None:
    extra_log = (
        db.query(ExtraFoodLog)
        .filter(
            ExtraFoodLog.id == extra_food_log_id,
            ExtraFoodLog.user_id == user.id,
        )
        .one_or_none()
    )

    if extra_log is None:
        raise extra_food_log_not_found_error()

    try:
        db.delete(extra_log)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise extra_food_log_save_failed_error() from exc
