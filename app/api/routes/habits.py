from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.habit import (HabitCompletionRequest, HabitCreateRequest, HabitDayResponse,
                               HabitHistoryResponse, HabitListResponse, HabitResponse, HabitUpdateRequest)
from app.services import habit_service

router = APIRouter()


@router.post("", response_model=HabitResponse, status_code=201)
def create(payload: HabitCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return habit_service.create_habit(db, user, payload)


@router.get("", response_model=HabitListResponse)
def list_daily(log_date: date | None = Query(None, alias="date"), limit: int = Query(100, ge=1, le=100),
               offset: int = Query(0, ge=0), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return habit_service.list_habits(db, user, log_date or datetime.now(timezone.utc).date(), limit, offset)


@router.patch("/{habit_id}", response_model=HabitResponse)
def update(habit_id: UUID, payload: HabitUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return habit_service.update_habit(db, user, habit_id, payload)


@router.delete("/{habit_id}", status_code=204)
def remove(habit_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    habit_service.delete_habit(db, user, habit_id)
    return Response(status_code=204)


@router.put("/{habit_id}/completions/{log_date}", response_model=HabitDayResponse)
def complete(habit_id: UUID, log_date: date, payload: HabitCompletionRequest,
             user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return habit_service.set_completion(db, user, habit_id, log_date, payload.completed)


@router.get("/{habit_id}/history", response_model=HabitHistoryResponse)
def history(habit_id: UUID, start_date: date | None = None, end_date: date | None = None,
            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return habit_service.habit_history(db, user, habit_id, start_date, end_date)
