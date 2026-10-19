from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.routes.recipes import candidate_result_to_response
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.ai import (
    AIMealOptionsResponse,
    NaturalLanguageConstraintRequest,
    NaturalLanguageMealConstraintResponse,
)
from app.services.ai_constraint_service import (
    interpret_natural_language_constraints,
    preview_ai_meal_options,
)


router = APIRouter()


@router.post(
    "/constraints/interpret",
    response_model=NaturalLanguageMealConstraintResponse,
)
def interpret_constraints(
    payload: NaturalLanguageConstraintRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NaturalLanguageMealConstraintResponse:
    interpreted = interpret_natural_language_constraints(
        db=db,
        user=current_user,
        text=payload.text,
        context_meal_type=payload.context_meal_type,
    )
    return interpreted.constraints


@router.post("/meal-options", response_model=AIMealOptionsResponse)
def ai_meal_options(
    payload: NaturalLanguageConstraintRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AIMealOptionsResponse:
    interpreted, candidate_result = preview_ai_meal_options(
        db=db,
        user=current_user,
        text=payload.text,
        context_meal_type=payload.context_meal_type,
    )
    return AIMealOptionsResponse(
        interpretation=interpreted.constraints,
        candidate_preview=(
            candidate_result_to_response(candidate_result)
            if candidate_result is not None
            else None
        ),
    )
