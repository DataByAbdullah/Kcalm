from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.integration import IntegrationListResponse, IntegrationStatusResponse
from app.services.integration_service import get_integration, list_integrations

router = APIRouter()


@router.get("", response_model=IntegrationListResponse)
def list_available(user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)):
    return {"items": list_integrations(settings)}


@router.get("/{code}", response_model=IntegrationStatusResponse)
def read_status(code: str, user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)):
    return get_integration(code, settings)
