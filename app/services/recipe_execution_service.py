from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.enums import MealPlanStatus, RecipeExecutionStatus, RecipeStepPhase
from app.core.exceptions import APIErrorException
from app.models.meal_plan import MealPlanItem
from app.models.recipe import Recipe, RecipeIngredient, RecipeStep, RecipeTagLink
from app.models.recipe_execution import RecipeExecutionSession, RecipeExecutionStepSnapshot
from app.models.user import User
from app.schemas.recipe_execution import RecipeExecutionStartRequest
from app.services.meal_plan_service import get_meal_plan_detail
from app.services.recipe_service import recipe_not_found_error


def execution_session_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="RECIPE_EXECUTION_SESSION_NOT_FOUND",
        message="Recipe execution session not found.",
    )


def meal_plan_item_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="MEAL_PLAN_ITEM_NOT_FOUND",
        message="Meal plan item not found.",
    )


def meal_plan_archived_for_execution_error() -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="MEAL_PLAN_ARCHIVED",
        message="Archived meal plans cannot start recipe execution sessions.",
    )


def execution_steps_missing_error(recipe_id: UUID) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="RECIPE_EXECUTION_STEPS_MISSING",
        message="Recipe execution requires at least one structured recipe step.",
        details={"recipe_id": str(recipe_id)},
    )


def active_execution_session_exists_error(session_id: UUID) -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="EXECUTION_SESSION_ALREADY_ACTIVE",
        message="An active execution session already exists for this meal-plan item.",
        details={"session_id": str(session_id)},
    )


def invalid_step_index_error(step_index: int, step_count: int) -> APIErrorException:
    return APIErrorException(
        status_code=422,
        code="INVALID_EXECUTION_STEP_INDEX",
        message="Execution step index is outside the session step range.",
        details={"current_step_index": step_index, "step_count": step_count},
    )


def execution_session_completed_error() -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="EXECUTION_SESSION_COMPLETED",
        message="Completed execution sessions cannot be modified.",
    )


def execution_session_abandoned_error() -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="EXECUTION_SESSION_ABANDONED",
        message="Abandoned execution sessions cannot be resumed or modified.",
    )


def execution_session_save_failed_error() -> APIErrorException:
    return APIErrorException(
        status_code=500,
        code="RECIPE_EXECUTION_SAVE_FAILED",
        message="Recipe execution session could not be saved.",
    )


def start_recipe_execution_session(
    db: Session,
    user: User,
    recipe_id: UUID,
    payload: RecipeExecutionStartRequest,
) -> RecipeExecutionSession:
    recipe = load_recipe_for_execution(db=db, recipe_id=recipe_id)
    if recipe is None or not recipe.active:
        raise recipe_not_found_error()
    ensure_recipe_has_steps(recipe)

    try:
        session = create_execution_snapshot(
            db=db,
            user=user,
            recipe=recipe,
            recipe_name_snapshot=recipe.name,
            servings=payload.servings,
            meal_plan_id=None,
            meal_plan_item_id=None,
            ingredient_summary=ingredient_summary_from_recipe(
                recipe=recipe,
                servings=payload.servings,
            ),
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise execution_session_save_failed_error() from exc
    except Exception:
        db.rollback()
        raise

    return get_execution_session(db=db, user=user, session_id=session.id)


def start_meal_plan_item_execution_session(
    db: Session,
    user: User,
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
) -> RecipeExecutionSession:
    plan = get_meal_plan_detail(db=db, user=user, meal_plan_id=meal_plan_id)
    if plan.status == MealPlanStatus.ARCHIVED.value:
        raise meal_plan_archived_for_execution_error()
    item = item_for_execution(plan_items=plan.items, meal_plan_item_id=meal_plan_item_id)
    active_session = active_session_for_meal_plan_item(db=db, meal_plan_item_id=item.id)
    if active_session is not None:
        raise active_execution_session_exists_error(active_session.id)

    recipe = load_recipe_for_execution(db=db, recipe_id=item.recipe_id)
    if recipe is None:
        raise recipe_not_found_error()
    ensure_recipe_has_steps(recipe)

    try:
        session = create_execution_snapshot(
            db=db,
            user=user,
            recipe=recipe,
            recipe_name_snapshot=item.recipe_name_snapshot,
            servings=item.servings,
            meal_plan_id=plan.id,
            meal_plan_item_id=item.id,
            ingredient_summary=ingredient_summary_from_meal_plan_item(item),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing_session = active_session_for_meal_plan_item(db=db, meal_plan_item_id=item.id)
        if existing_session is not None:
            raise active_execution_session_exists_error(existing_session.id) from exc
        raise execution_session_save_failed_error() from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise execution_session_save_failed_error() from exc
    except Exception:
        db.rollback()
        raise

    return get_execution_session(db=db, user=user, session_id=session.id)


def get_execution_session(
    db: Session,
    user: User,
    session_id: UUID,
) -> RecipeExecutionSession:
    session = (
        db.query(RecipeExecutionSession)
        .options(selectinload(RecipeExecutionSession.step_snapshots))
        .filter(
            RecipeExecutionSession.id == session_id,
            RecipeExecutionSession.user_id == user.id,
        )
        .one_or_none()
    )
    if session is None:
        raise execution_session_not_found_error()
    return session


def update_execution_progress(
    db: Session,
    user: User,
    session_id: UUID,
    current_step_index: int,
) -> RecipeExecutionSession:
    session = get_execution_session(db=db, user=user, session_id=session_id)
    ensure_session_can_progress(session)
    ensure_valid_step_index(session=session, step_index=current_step_index)
    session.current_step_index = current_step_index
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise execution_session_save_failed_error() from exc
    return get_execution_session(db=db, user=user, session_id=session.id)


def complete_execution_step(
    db: Session,
    user: User,
    session_id: UUID,
    step_index: int,
) -> RecipeExecutionSession:
    session = get_execution_session(db=db, user=user, session_id=session_id)
    ensure_session_can_progress(session)
    ensure_valid_step_index(session=session, step_index=step_index)
    step = step_by_index(session=session, step_index=step_index)
    now = datetime.now(timezone.utc)
    step.completed = True
    step.completed_at = step.completed_at or now
    if step_index < len(session.step_snapshots) - 1:
        session.current_step_index = max(session.current_step_index, step_index + 1)
    else:
        session.current_step_index = step_index

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise execution_session_save_failed_error() from exc
    return get_execution_session(db=db, user=user, session_id=session.id)


def complete_execution_session(
    db: Session,
    user: User,
    session_id: UUID,
) -> RecipeExecutionSession:
    session = get_execution_session(db=db, user=user, session_id=session_id)
    if session.status == RecipeExecutionStatus.ABANDONED.value:
        raise execution_session_abandoned_error()
    if session.status == RecipeExecutionStatus.COMPLETED.value:
        return session

    now = datetime.now(timezone.utc)
    session.status = RecipeExecutionStatus.COMPLETED.value
    session.completed_at = now
    session.current_step_index = max(len(session.step_snapshots) - 1, 0)
    for step in session.step_snapshots:
        step.completed = True
        step.completed_at = step.completed_at or now

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise execution_session_save_failed_error() from exc
    return get_execution_session(db=db, user=user, session_id=session.id)


def abandon_execution_session(
    db: Session,
    user: User,
    session_id: UUID,
) -> RecipeExecutionSession:
    session = get_execution_session(db=db, user=user, session_id=session_id)
    if session.status == RecipeExecutionStatus.COMPLETED.value:
        raise execution_session_completed_error()
    if session.status == RecipeExecutionStatus.ABANDONED.value:
        return session

    session.status = RecipeExecutionStatus.ABANDONED.value
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise execution_session_save_failed_error() from exc
    return get_execution_session(db=db, user=user, session_id=session.id)


def load_recipe_for_execution(db: Session, recipe_id: UUID) -> Recipe | None:
    return (
        db.query(Recipe)
        .options(
            selectinload(Recipe.ingredients).selectinload(RecipeIngredient.food),
            selectinload(Recipe.steps),
            selectinload(Recipe.equipment),
            selectinload(Recipe.tag_links).selectinload(RecipeTagLink.tag),
        )
        .filter(Recipe.id == recipe_id)
        .one_or_none()
    )


def create_execution_snapshot(
    db: Session,
    user: User,
    recipe: Recipe,
    recipe_name_snapshot: str,
    servings: float,
    meal_plan_id: UUID | None,
    meal_plan_item_id: UUID | None,
    ingredient_summary: list[dict],
) -> RecipeExecutionSession:
    session = RecipeExecutionSession(
        user_id=user.id,
        recipe_id=recipe.id,
        meal_plan_id=meal_plan_id,
        meal_plan_item_id=meal_plan_item_id,
        recipe_name_snapshot=recipe_name_snapshot,
        servings=servings,
        status=RecipeExecutionStatus.IN_PROGRESS.value,
        current_step_index=0,
        total_estimated_time_minutes=recipe.total_time_minutes,
        required_equipment_snapshot=sorted(item.equipment for item in recipe.equipment),
        ingredient_summary_snapshot=ingredient_summary,
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.flush()
    for step_index, step in enumerate(recipe.steps):
        db.add(
            RecipeExecutionStepSnapshot(
                execution_session_id=session.id,
                recipe_step_id=step.id,
                step_index=step_index,
                recipe_step_position=step.position,
                instruction_snapshot=step.instruction,
                phase=step.phase or RecipeStepPhase.COOK.value,
                duration_seconds=step.duration_seconds,
                timer_required=step.timer or step.timer_seconds is not None,
                timer_seconds=step.timer_seconds,
                completed=False,
                equipment_snapshot=[],
                ingredient_references_snapshot=[],
                cue_action=step.cue_action,
                animation_key=step.animation_key,
                media_asset_key=step.media_asset_key,
                visual_cue=step.visual_cue,
            )
        )
    db.flush()
    return session


def ensure_recipe_has_steps(recipe: Recipe) -> None:
    if not recipe.steps:
        raise execution_steps_missing_error(recipe.id)


def ensure_session_can_progress(session: RecipeExecutionSession) -> None:
    if session.status == RecipeExecutionStatus.COMPLETED.value:
        raise execution_session_completed_error()
    if session.status == RecipeExecutionStatus.ABANDONED.value:
        raise execution_session_abandoned_error()


def ensure_valid_step_index(session: RecipeExecutionSession, step_index: int) -> None:
    if step_index < 0 or step_index >= len(session.step_snapshots):
        raise invalid_step_index_error(step_index=step_index, step_count=len(session.step_snapshots))


def step_by_index(
    session: RecipeExecutionSession,
    step_index: int,
) -> RecipeExecutionStepSnapshot:
    for step in session.step_snapshots:
        if step.step_index == step_index:
            return step
    raise invalid_step_index_error(step_index=step_index, step_count=len(session.step_snapshots))


def item_for_execution(
    plan_items: list[MealPlanItem],
    meal_plan_item_id: UUID,
) -> MealPlanItem:
    for item in plan_items:
        if item.id == meal_plan_item_id:
            return item
    raise meal_plan_item_not_found_error()


def active_session_for_meal_plan_item(
    db: Session,
    meal_plan_item_id: UUID,
) -> RecipeExecutionSession | None:
    return (
        db.query(RecipeExecutionSession)
        .filter(
            RecipeExecutionSession.meal_plan_item_id == meal_plan_item_id,
            RecipeExecutionSession.status.in_(
                [
                    RecipeExecutionStatus.NOT_STARTED.value,
                    RecipeExecutionStatus.IN_PROGRESS.value,
                ]
            ),
        )
        .one_or_none()
    )


def ingredient_summary_from_recipe(recipe: Recipe, servings: float) -> list[dict]:
    summaries: list[dict] = []
    for ingredient in recipe.ingredients:
        summaries.append(
            {
                "ingredient_id": str(ingredient.id),
                "food_id": str(ingredient.food_id),
                "food_name": ingredient.food.name,
                "quantity_grams": float(ingredient.quantity_grams) * servings,
                "display_quantity": ingredient.display_quantity,
                "display_unit": ingredient.display_unit,
                "preparation_note": ingredient.preparation_note,
            }
        )
    return summaries


def ingredient_summary_from_meal_plan_item(item: MealPlanItem) -> list[dict]:
    return [
        {
            "ingredient_id": None,
            "food_id": str(snapshot.food_id),
            "food_name": snapshot.food_name_snapshot,
            "quantity_grams": snapshot.quantity_grams,
            "display_quantity": None,
            "display_unit": "g",
            "preparation_note": None,
        }
        for snapshot in item.ingredient_snapshots
    ]
