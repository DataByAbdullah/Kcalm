from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import APIErrorException
from app.core.security import get_current_user
from app.models.user import User
from app.nutrition.bmr import round_nutrition_output
from app.nutrition.errors import NutritionCalculationError
from app.nutrition.micronutrients import (
    MicronutrientReferenceDataError,
    MicronutrientTarget,
    MicronutrientTargetError,
    get_micronutrient_targets,
)
from app.nutrition.targets import calculate_nutrition_targets
from app.schemas.nutrition import (
    MacroTargetsResponse,
    MicronutrientTargetResponse,
    MicronutrientTargetsResponse,
    NutritionCalculationRequest,
    NutritionCalculationResponse,
)
from app.services.user_profile_service import get_profile


router = APIRouter()


def _micronutrient_to_response(target: MicronutrientTarget) -> MicronutrientTargetResponse:
    return MicronutrientTargetResponse(
        code=target.nutrient_code,
        name=target.nutrient_name,
        target=target.amount,
        unit=target.unit,
        minimum_target=target.minimum_target,
        upper_limit=target.upper_limit,
        upper_limit_unit=target.upper_limit_unit,
        target_type=target.target_type,
        upper_limit_type=target.upper_limit_type,
        age_min=target.age_min,
        age_max=target.age_max,
        sex=target.sex,
        source=target.source,
        source_url=target.source_url,
        source_version=target.source_version,
        note=target.note,
    )


@router.post("/calculate", response_model=NutritionCalculationResponse)
def calculate_nutrition(
    payload: NutritionCalculationRequest,
    _current_user: User = Depends(get_current_user),
) -> NutritionCalculationResponse:
    try:
        targets = calculate_nutrition_targets(
            age=payload.age,
            sex=payload.sex,
            height_cm=payload.height_cm,
            weight_kg=payload.weight_kg,
            activity_level=payload.activity_level,
            goal=payload.goal,
            target_rate=payload.target_rate,
        )
    except NutritionCalculationError as exc:
        raise APIErrorException(
            status_code=422,
            code="NUTRITION_CALCULATION_ERROR",
            message=str(exc),
        ) from exc

    return NutritionCalculationResponse(
        bmr=round_nutrition_output(targets.bmr),
        tdee=round_nutrition_output(targets.tdee),
        target_calories=round_nutrition_output(targets.target_calories),
        macros=MacroTargetsResponse(
            protein_g=round_nutrition_output(targets.macros.protein_g),
            carbs_g=round_nutrition_output(targets.macros.carbs_g),
            fat_g=round_nutrition_output(targets.macros.fat_g),
        ),
    )


@router.get("/micronutrients", response_model=MicronutrientTargetsResponse)
def read_micronutrient_targets(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MicronutrientTargetsResponse:
    profile = get_profile(db=db, user=current_user)

    try:
        targets = get_micronutrient_targets(age=profile.age, sex=profile.sex)
    except MicronutrientTargetError as exc:
        raise APIErrorException(
            status_code=422,
            code="MICRONUTRIENT_TARGETS_UNSUPPORTED",
            message=str(exc),
        ) from exc
    except MicronutrientReferenceDataError as exc:
        raise APIErrorException(
            status_code=500,
            code="MICRONUTRIENT_REFERENCE_DATA_MISSING",
            message="Micronutrient reference data is incomplete.",
            details={"reason": str(exc)},
        ) from exc

    return MicronutrientTargetsResponse(
        micronutrients=[_micronutrient_to_response(target) for target in targets]
    )
