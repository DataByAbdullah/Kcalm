from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.daily_metrics import (
    DailyMetricsHistoryResponse, DailyMetricsRequest, DailyMetricsResponse,
)
from app.services.daily_metrics_service import (
    daily_metrics_history, delete_daily_metrics, get_daily_metrics, save_daily_metrics,
)


router = APIRouter()


@router.put("/{log_date}", response_model=DailyMetricsResponse)
def put_metrics(log_date: date, payload: DailyMetricsRequest,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_daily_metrics(db, user, log_date, payload)


@router.get("", response_model=DailyMetricsHistoryResponse)
def history(start_date: date | None = Query(None, alias="from"),
            end_date: date | None = Query(None, alias="to"),
            limit: int = Query(100, ge=1, le=365), offset: int = Query(0, ge=0),
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return daily_metrics_history(db, user, start_date, end_date, limit, offset)


@router.get("/{log_date}", response_model=DailyMetricsResponse)
def read_metrics(log_date: date, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_daily_metrics(db, user, log_date)


@router.delete("/{log_date}", status_code=204)
def remove_metrics(log_date: date, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_daily_metrics(db, user, log_date)
    return Response(status_code=204)
