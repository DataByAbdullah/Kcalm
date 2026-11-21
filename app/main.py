from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import DEFAULT_JWT_SECRET, get_settings
from app.core.exceptions import (
    APIErrorException,
    api_error_exception_handler,
    build_error_response,
)
from app.services.email_service import warn_if_email_unconfigured
from app.services.password_reset_dispatch import password_reset_lifespan
from app.core.password_reset_logging import configure_password_reset_logging


def sanitize_validation_errors(errors: list[dict]) -> list[dict]:
    sanitized_errors = []
    for error in errors:
        sanitized_errors.append(
            {
                key: value
                for key, value in error.items()
                if key not in {"input", "ctx"}
            }
        )
    return sanitized_errors


def create_app() -> FastAPI:
    configure_password_reset_logging()
    settings = get_settings()
    if settings.is_production and settings.jwt_secret == DEFAULT_JWT_SECRET:
        raise RuntimeError("JWT_SECRET must be changed from the development default in production.")
    if settings.is_production:
        warn_if_email_unconfigured(settings)

    app = FastAPI(
        lifespan=password_reset_lifespan,
        title=settings.app_name,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Retry-After"],
    )
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.add_exception_handler(APIErrorException, api_error_exception_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        if request.method == "PUT" and request.url.path.endswith("/users/me/avatar"):
            # Never echo request values, decoder details, or image contents.
            return build_error_response(422, "INVALID_AVATAR", "Provide a valid avatar image Data URL.")
        error_code = "VALIDATION_ERROR"
        if request.url.path.endswith("/users/profile"):
            error_code = "INVALID_PROFILE_DATA"
        return build_error_response(
            status_code=422,
            code=error_code,
            message="Request validation failed.",
            details={"errors": sanitize_validation_errors(exc.errors())},
        )

    return app


app = create_app()
