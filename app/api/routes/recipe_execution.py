from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import RecipeExecutionStatus, RecipeStepPhase
from app.core.security import get_current_user
from app.models.recipe_execution import RecipeExecutionSession, RecipeExecutionStepSnapshot
from app.models.user import User
from app.schemas.recipe_execution import (
    RecipeExecutionIngredientSummaryResponse,
    RecipeExecutionProgressRequest,
    RecipeExecutionProgressResponse,
    RecipeExecutionSessionResponse,
    RecipeExecutionStartRequest,
    RecipeExecutionStepResponse,
)
from app.services.recipe_execution_service import (
    abandon_execution_session,
    complete_execution_session,
    complete_execution_step,
    get_execution_session,
    start_meal_plan_item_execution_session,
    start_recipe_execution_session,
    update_execution_progress,
)


router = APIRouter()


def execution_progress_response(
    steps: list[RecipeExecutionStepSnapshot],
) -> RecipeExecutionProgressResponse:
    total_steps = len(steps)
    completed_steps = sum(1 for step in steps if step.completed)
    percent_complete = 0.0 if total_steps == 0 else (completed_steps / total_steps) * 100
    return RecipeExecutionProgressResponse(
        completed_steps=completed_steps,
        total_steps=total_steps,
        percent_complete=percent_complete,
    )


def execution_session_to_response(
    session: RecipeExecutionSession,
) -> RecipeExecutionSessionResponse:
    steps = list(session.step_snapshots)
    ingredients = [
        RecipeExecutionIngredientSummaryResponse.model_validate(item)
        for item in session.ingredient_summary_snapshot
    ]
    return RecipeExecutionSessionResponse(
        session_id=session.id,
        recipe_id=session.recipe_id,
        meal_plan_id=session.meal_plan_id,
        meal_plan_item_id=session.meal_plan_item_id,
        recipe_name=session.recipe_name_snapshot,
        servings=session.servings,
        status=RecipeExecutionStatus(session.status),
        current_step_index=session.current_step_index,
        total_estimated_time_minutes=session.total_estimated_time_minutes,
        required_equipment=list(session.required_equipment_snapshot or []),
        ingredients=ingredients,
        step_count=len(steps),
        progress=execution_progress_response(steps),
        steps=[execution_step_to_response(step) for step in steps],
        started_at=session.started_at,
        completed_at=session.completed_at,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def execution_step_to_response(
    step: RecipeExecutionStepSnapshot,
) -> RecipeExecutionStepResponse:
    return RecipeExecutionStepResponse(
        id=step.id,
        step_index=step.step_index,
        recipe_step_position=step.recipe_step_position,
        instruction=step.instruction_snapshot,
        phase=RecipeStepPhase(step.phase),
        duration_seconds=step.duration_seconds,
        timer_required=step.timer_required,
        timer_seconds=step.timer_seconds,
        completed=step.completed,
        completed_at=step.completed_at,
        equipment=list(step.equipment_snapshot or []),
        ingredients=list(step.ingredient_references_snapshot or []),
        cue_action=step.cue_action,
        animation_key=step.animation_key,
        media_asset_key=step.media_asset_key,
        visual_cue=step.visual_cue,
        timer_started_at=step.timer_started_at,
        timer_completed_at=step.timer_completed_at,
    )


@router.post(
    "/recipes/{recipe_id}/execution-sessions",
    response_model=RecipeExecutionSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_direct_recipe_execution(
    recipe_id: UUID,
    payload: RecipeExecutionStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeExecutionSessionResponse:
    session = start_recipe_execution_session(
        db=db,
        user=current_user,
        recipe_id=recipe_id,
        payload=payload,
    )
    return execution_session_to_response(session)


@router.post(
    "/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/execution-session",
    response_model=RecipeExecutionSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_meal_plan_item_execution(
    meal_plan_id: UUID,
    meal_plan_item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeExecutionSessionResponse:
    session = start_meal_plan_item_execution_session(
        db=db,
        user=current_user,
        meal_plan_id=meal_plan_id,
        meal_plan_item_id=meal_plan_item_id,
    )
    return execution_session_to_response(session)


@router.get(
    "/recipe-execution-sessions/{session_id}",
    response_model=RecipeExecutionSessionResponse,
)
def read_execution_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeExecutionSessionResponse:
    session = get_execution_session(db=db, user=current_user, session_id=session_id)
    return execution_session_to_response(session)


@router.patch(
    "/recipe-execution-sessions/{session_id}/progress",
    response_model=RecipeExecutionSessionResponse,
)
def patch_execution_progress(
    session_id: UUID,
    payload: RecipeExecutionProgressRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeExecutionSessionResponse:
    session = update_execution_progress(
        db=db,
        user=current_user,
        session_id=session_id,
        current_step_index=payload.current_step_index,
    )
    return execution_session_to_response(session)


@router.post(
    "/recipe-execution-sessions/{session_id}/steps/{step_index}/complete",
    response_model=RecipeExecutionSessionResponse,
)
def complete_execution_step_endpoint(
    session_id: UUID,
    step_index: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeExecutionSessionResponse:
    session = complete_execution_step(
        db=db,
        user=current_user,
        session_id=session_id,
        step_index=step_index,
    )
    return execution_session_to_response(session)


@router.post(
    "/recipe-execution-sessions/{session_id}/complete",
    response_model=RecipeExecutionSessionResponse,
)
def complete_execution_session_endpoint(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeExecutionSessionResponse:
    session = complete_execution_session(db=db, user=current_user, session_id=session_id)
    return execution_session_to_response(session)


@router.post(
    "/recipe-execution-sessions/{session_id}/abandon",
    response_model=RecipeExecutionSessionResponse,
)
def abandon_execution_session_endpoint(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecipeExecutionSessionResponse:
    session = abandon_execution_session(db=db, user=current_user, session_id=session_id)
    return execution_session_to_response(session)
