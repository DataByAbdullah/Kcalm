from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.schemas.errors import APIError, APIErrorResponse


class APIErrorException(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


def build_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    error_response = APIErrorResponse(
        error=APIError(
            code=code,
            message=message,
            details=details or {},
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=error_response.model_dump(),
        headers=headers,
    )


async def api_error_exception_handler(
    request: Request,
    exc: APIErrorException,
) -> JSONResponse:
    return build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        headers=exc.headers,
    )


def unauthorized_error(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> APIErrorException:
    return APIErrorException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code=code,
        message=message,
        details=details,
        headers={"WWW-Authenticate": "Bearer"},
    )
