from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.progress import InsightsResponse
from app.services.insight_service import get_insights

router = APIRouter()


@router.get("", response_model=InsightsResponse)
def insights(start_date: date | None = None, end_date: date | None = None,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_insights(db, user, start_date, end_date)
