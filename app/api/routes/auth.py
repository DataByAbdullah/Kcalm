from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from uuid import UUID
from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    InvalidTokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_current_user,
)
from app.core.exceptions import APIErrorException, unauthorized_error
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    RefreshTokenRequest,
    ForgotPasswordRequest,
    MessageResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.services.auth_service import (
    change_password,
    authenticate_user,
    register_user,
    request_password_reset,
    reset_password,
)


router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegisterRequest,
    db: Session = Depends(get_db),
) -> User:
    return register_user(
        db=db,
        email=str(payload.email),
        password=payload.password,
        full_name=payload.full_name,
)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: UserLoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    user = authenticate_user(
        db=db,
        email=str(payload.email),
        password=payload.password,
        )
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_expires_in=settings.refresh_token_expire_days * 24 * 60 * 60,
)


@router.post("/refresh", response_model=TokenResponse)
def refresh_access_token(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    try:
        token_payload = decode_refresh_token(payload.refresh_token)
        user_id = UUID(str(token_payload.get("sub")))
    except TokenExpiredError as exc:
        raise unauthorized_error(
            code="REFRESH_TOKEN_EXPIRED",
            message="Refresh token has expired.",
        ) from exc
    except (InvalidTokenError, TypeError, ValueError) as exc:
        raise unauthorized_error(
            code="INVALID_REFRESH_TOKEN",
            message="Refresh token is invalid.",
        ) from exc

    user = db.get(User, user_id)

    if user is None or token_payload.get("ver", 0) != user.token_version:
        raise unauthorized_error(
            code="INVALID_REFRESH_TOKEN",
            message="Refresh token is invalid.",
        )

    if not user.is_active:
        raise APIErrorException(
            status_code=403,
            code="USER_INACTIVE",
            message="This account is inactive.",
        )

    settings = get_settings()

    return TokenResponse(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
        expires_in=settings.access_token_expire_minutes * 60,
        refresh_expires_in=settings.refresh_token_expire_days * 24 * 60 * 60,
    )


@router.get("/me", response_model=UserResponse)
def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/change-password", response_model=MessageResponse)
def change_current_password(payload: ChangePasswordRequest, current_user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    change_password(db, current_user, payload.current_password, payload.new_password)
    return MessageResponse(message="Password changed. Sign in again.")

@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    request_password_reset(
        db=db,
        email=str(payload.email),
    )

    return MessageResponse(
        message="If an account exists for this email, a password reset link has been sent."
    )


@router.post("/reset-password", response_model=MessageResponse)
def reset_user_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    reset_password(
        db=db,
        token=payload.token,
        new_password=payload.new_password,
    )

    return MessageResponse(
        message="Password has been reset successfully."
    )
