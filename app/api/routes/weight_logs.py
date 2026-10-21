from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.tracking import WeightHistoryResponse, WeightLogRequest, WeightLogResponse
from app.services.weight_service import delete_weight, save_weight, weight_history

router = APIRouter()


@router.put("/{log_date}", response_model=WeightLogResponse)
def put_weight(log_date: date, payload: WeightLogRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_weight(db, user, log_date, payload)


@router.get("", response_model=WeightHistoryResponse)
def get_weights(start_date: date | None = None, end_date: date | None = None,
                limit: int = Query(100, ge=1, le=365), offset: int = Query(0, ge=0),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return weight_history(db, user, start_date, end_date, limit, offset)


@router.delete("/{log_date}", status_code=204)
def remove_weight(log_date: date, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_weight(db, user, log_date)
    return Response(status_code=204)
