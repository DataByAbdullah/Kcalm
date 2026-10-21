from datetime import date
from uuid import UUID

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import APIErrorException
from app.models.user import User
from app.models.weight_log import WeightLog
from app.models.step_log import StepLog
from app.models.habit import HabitCompletion
from app.models.notification import Notification
from app.schemas.tracking import WeightLogRequest, StepLogRequest
from app.services.weight_service import save_weight
from app.services.step_service import save_steps
from app.services.habit_service import set_completion
from app.services.notification_service import sync_notifications
from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user


@pytest.mark.parametrize("operation", ["weight", "steps", "habit", "notifications"])
def test_tracking_writes_rollback_on_commit_failure(tracking_user, monkeypatch, operation):
    db, token = tracking_user
    user_id = UUID(request("GET", "/auth/me", token).json()["id"])
    user = db.get(User, user_id)
    habit_id = UUID(request("POST", "/habits", token, {"name": "Walk", "start_date": "2026-01-01"}).json()["id"])
    if operation == "notifications":
        request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": 80})
    def fail_commit():
        raise SQLAlchemyError("forced failure")
    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail_commit)
        with pytest.raises(APIErrorException) as error:
            if operation == "weight":
                save_weight(db, user, date(2026, 1, 1), WeightLogRequest(weight_kg=80))
            elif operation == "steps":
                save_steps(db, user, date(2026, 1, 1), StepLogRequest(steps=5000))
            elif operation == "habit":
                set_completion(db, user, habit_id, date(2026, 1, 1), True)
            else:
                sync_notifications(db, user)
        assert error.value.code == "TRACKING_SAVE_FAILED"
    model = {"weight": WeightLog, "steps": StepLog, "habit": HabitCompletion, "notifications": Notification}[operation]
    query = db.query(model)
    query = query.filter_by(habit_id=habit_id) if operation == "habit" else query.filter_by(user_id=user_id)
    assert query.count() == 0
