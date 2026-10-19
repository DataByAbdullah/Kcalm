from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import (
    APIErrorException,
    api_error_exception_handler,
    build_error_response,
)


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
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.add_exception_handler(APIErrorException, api_error_exception_handler)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
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
