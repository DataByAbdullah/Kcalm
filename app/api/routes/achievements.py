from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.progress import AchievementsResponse
from app.services.achievement_service import get_achievements

router = APIRouter()


@router.get("", response_model=AchievementsResponse)
def achievements(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"items": get_achievements(db, user)}
