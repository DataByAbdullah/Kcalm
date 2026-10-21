from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import APIErrorException
from app.models.user import User
from app.models.user_profile import (
    UserAllergy,
    UserDietaryRestriction,
    UserDislikedFood,
    UserEquipment,
    UserPreferredFood,
    UserProfile,
)
from app.schemas.user_profile import (
    UserProfileCreateRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
)


SCALAR_PROFILE_FIELDS = {
    "age",
    "sex",
    "height_cm",
    "weight_kg",
    "target_weight_kg",
    "activity_level",
    "goal",
    "target_rate",
    "max_cooking_minutes",
    "meals_per_day",
}

LIST_RELATIONSHIPS = {
    "allergies": (UserAllergy, "name"),
    "dietary_restrictions": (UserDietaryRestriction, "name"),
    "preferred_foods": (UserPreferredFood, "name"),
    "disliked_foods": (UserDislikedFood, "name"),
    "equipment": (UserEquipment, "equipment"),
}

USER_LOAD_OPTIONS = (
    selectinload(User.profile),
    selectinload(User.allergies),
    selectinload(User.dietary_restrictions),
    selectinload(User.preferred_foods),
    selectinload(User.disliked_foods),
    selectinload(User.equipment),
)


def _profile_already_exists_error() -> APIErrorException:
    return APIErrorException(
        status_code=409,
        code="PROFILE_ALREADY_EXISTS",
        message="A profile already exists for this user.",
    )


def _profile_not_found_error() -> APIErrorException:
    return APIErrorException(
        status_code=404,
        code="PROFILE_NOT_FOUND",
        message="Profile not found for this user.",
    )


def load_user_with_profile_data(db: Session, user_id: UUID) -> User:
    user = db.query(User).options(*USER_LOAD_OPTIONS).filter(User.id == user_id).one_or_none()
    if user is None:
        raise _profile_not_found_error()
    return user


def profile_to_response(user: User) -> UserProfileResponse:
    profile = user.profile
    if profile is None:
        raise _profile_not_found_error()

    return UserProfileResponse(
        age=profile.age,
        sex=profile.sex,
        height_cm=profile.height_cm,
        weight_kg=profile.weight_kg,
        target_weight_kg=profile.target_weight_kg,
        activity_level=profile.activity_level,
        goal=profile.goal,
        target_rate=profile.target_rate,
        max_cooking_minutes=profile.max_cooking_minutes,
        meals_per_day=profile.meals_per_day,
        allergies=sorted(item.name for item in user.allergies),
        dietary_restrictions=sorted(item.name for item in user.dietary_restrictions),
        preferred_foods=sorted(item.name for item in user.preferred_foods),
        disliked_foods=sorted(item.name for item in user.disliked_foods),
        equipment=sorted(item.equipment for item in user.equipment),
    )


def _replace_list(db: Session, user_id: UUID, field_name: str, values: list[str]) -> None:
    model, value_column = LIST_RELATIONSHIPS[field_name]
    db.query(model).filter(model.user_id == user_id).delete(synchronize_session=False)
    for value in values:
        db.add(model(user_id=user_id, **{value_column: value}))


def create_profile(
    db: Session,
    user: User,
    payload: UserProfileCreateRequest,
) -> UserProfileResponse:
    existing_profile = db.query(UserProfile).filter(UserProfile.user_id == user.id).one_or_none()
    if existing_profile is not None:
        raise _profile_already_exists_error()

    profile_data = payload.model_dump(include=SCALAR_PROFILE_FIELDS)
    profile = UserProfile(user_id=user.id, **profile_data)

    try:
        db.add(profile)
        for field_name in LIST_RELATIONSHIPS:
            _replace_list(db, user.id, field_name, getattr(payload, field_name))
        db.commit()
        db.expire_all()
    except IntegrityError as exc:
        db.rollback()
        raise _profile_already_exists_error() from exc
    except Exception:
        db.rollback()
        raise

    return get_profile(db, user)


def get_profile(db: Session, user: User) -> UserProfileResponse:
    loaded_user = load_user_with_profile_data(db, user.id)
    return profile_to_response(loaded_user)


def update_profile(
    db: Session,
    user: User,
    payload: UserProfileUpdateRequest,
) -> UserProfileResponse:
    loaded_user = load_user_with_profile_data(db, user.id)
    if loaded_user.profile is None:
        raise _profile_not_found_error()

    fields_set = payload.model_fields_set
    try:
        for field_name in SCALAR_PROFILE_FIELDS.intersection(fields_set):
            setattr(loaded_user.profile, field_name, getattr(payload, field_name))

        for field_name in LIST_RELATIONSHIPS:
            if field_name in fields_set:
                _replace_list(db, user.id, field_name, getattr(payload, field_name) or [])

        db.commit()
        db.expire_all()
    except Exception:
        db.rollback()
        raise

    return get_profile(db, user)
