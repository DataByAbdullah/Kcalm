from typing import Literal

from pydantic import BaseModel


class IntegrationStatusResponse(BaseModel):
    code: str
    name: str
    capabilities: list[str]
    status: Literal["configured", "not_configured", "not_implemented"]
    connection_verified: bool = False


class IntegrationListResponse(BaseModel):
    items: list[IntegrationStatusResponse]
