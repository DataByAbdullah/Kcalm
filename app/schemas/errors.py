from typing import Any

from pydantic import BaseModel, Field


class APIError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class APIErrorResponse(BaseModel):
    error: APIError

