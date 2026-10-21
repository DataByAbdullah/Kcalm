from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.tracking import StepHistoryResponse, StepLogRequest, StepLogResponse
from app.services.step_service import delete_steps, get_steps, save_steps, step_history

router = APIRouter()


@router.put("/{log_date}", response_model=StepLogResponse)
def put_steps(log_date: date, payload: StepLogRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return save_steps(db, user, log_date, payload)


@router.get("", response_model=StepHistoryResponse)
def get_history(start_date: date | None = None, end_date: date | None = None,
                limit: int = Query(100, ge=1, le=365), offset: int = Query(0, ge=0),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return step_history(db, user, start_date, end_date, limit, offset)


@router.get("/{log_date}", response_model=StepLogResponse)
def read_steps(log_date: date, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_steps(db, user, log_date)


@router.delete("/{log_date}", status_code=204)
def remove_steps(log_date: date, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    delete_steps(db, user, log_date)
    return Response(status_code=204)
