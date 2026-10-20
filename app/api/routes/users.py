from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.schemas.auth import UserResponse, UserUpdateRequest
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.user_profile import (
    UserProfileCreateRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
)
from app.services.user_profile_service import create_profile, get_profile, update_profile


router = APIRouter()

@router.patch("/me", response_model=UserResponse)
def update_current_user(
    payload: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    current_user.full_name = (
        " ".join(payload.full_name.strip().split())
        if payload.full_name
        else None
    )

    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return current_user

@router.post("/profile", response_model=UserProfileResponse, status_code=status.HTTP_201_CREATED)
def create_user_profile(
    payload: UserProfileCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    return create_profile(db=db, user=current_user, payload=payload)


@router.get("/profile", response_model=UserProfileResponse)
def read_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    return get_profile(db=db, user=current_user)


@router.patch("/profile", response_model=UserProfileResponse)
def update_user_profile(
    payload: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileResponse:
    return update_profile(db=db, user=current_user, payload=payload)
