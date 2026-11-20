from fastapi import APIRouter, Depends, Response, status
from app.services.account_service import delete_account, export_user_data
from app.schemas.account import UserDataExportResponse
from sqlalchemy.orm import Session
from app.schemas.auth import UserResponse, UserUpdateRequest
from app.core.database import get_db
from app.core.rate_limits import rate_limit_avatar
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.user_profile import (
    UserProfileCreateRequest,
    UserProfileResponse,
    UserProfileWithAvatarResponse,
    UserProfileUpdateRequest,
)
from app.services.user_profile_service import create_profile, get_profile, update_profile
from app.schemas.avatar import AvatarUploadRequest
from app.schemas.errors import APIErrorResponse
from app.api.avatar_request import read_avatar_request
from app.services.avatar_service import normalize_avatar_data_url, save_avatar


router = APIRouter()


def profile_with_avatar(profile: UserProfileResponse, user: User) -> UserProfileWithAvatarResponse:
    return UserProfileWithAvatarResponse(**profile.model_dump(), avatar=user.avatar_data_url)


@router.put(
    "/me/avatar", response_model=UserResponse,
    responses={422: {"model": APIErrorResponse}},
    openapi_extra={"requestBody": {"required": True, "content": {
        "application/json": {"schema": AvatarUploadRequest.model_json_schema()},
    }}},
)
def upload_current_user_avatar(
    response: Response,
    payload: AvatarUploadRequest = Depends(read_avatar_request),
    current_user: User = Depends(rate_limit_avatar),
    db: Session = Depends(get_db),
) -> User:
    avatar = normalize_avatar_data_url(payload.image)
    response.headers["Cache-Control"] = "no-store"
    return save_avatar(db, current_user, avatar)


@router.delete("/me/avatar", status_code=204)
def delete_current_user_avatar(
    current_user: User = Depends(rate_limit_avatar),
    db: Session = Depends(get_db),
) -> Response:
    save_avatar(db, current_user, None)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/me/export", response_model=UserDataExportResponse)
def export_current_user(response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers["Content-Disposition"] = 'attachment; filename="kcalm-data.json"'
    response.headers["Cache-Control"] = "no-store"
    return export_user_data(db, current_user)


@router.delete("/me", status_code=204)
def delete_current_user(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_account(db, current_user)
    return Response(status_code=204)

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

@router.post("/profile", response_model=UserProfileWithAvatarResponse, status_code=status.HTTP_201_CREATED)
def create_user_profile(
    payload: UserProfileCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileWithAvatarResponse:
    return profile_with_avatar(create_profile(db=db, user=current_user, payload=payload), current_user)


@router.get("/profile", response_model=UserProfileWithAvatarResponse)
def read_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileWithAvatarResponse:
    return profile_with_avatar(get_profile(db=db, user=current_user), current_user)


@router.patch("/profile", response_model=UserProfileWithAvatarResponse)
def update_user_profile(
    payload: UserProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfileWithAvatarResponse:
    return profile_with_avatar(update_profile(db=db, user=current_user, payload=payload), current_user)
