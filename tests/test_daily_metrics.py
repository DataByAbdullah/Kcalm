from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.models.daily_metrics import DailyMetrics
from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import register_and_login, unique_email


BODY = {"water_glasses": 8, "fruit_veg_servings": 5, "sleep_hours": 7.5}


def test_daily_metrics_upsert_full_replacement_history_and_ownership(tracking_user, auth_db):
    db, token = tracking_user
    path = "/daily-metrics/2026-01-02"
    saved = request("PUT", path, token, BODY)
    assert saved.status_code == 200, saved.text
    assert request("PUT", path, token, BODY).json()["id"] == saved.json()["id"]
    replacement = {"water_glasses": 0, "fruit_veg_servings": 1.5, "sleep_hours": 0}
    updated = request("PUT", path, token, replacement).json()
    assert updated["id"] == saved.json()["id"]
    assert updated["created_at"] == saved.json()["created_at"]
    assert all(updated[field] == value for field, value in replacement.items())
    assert request("GET", path, token).json() == updated
    request("PUT", "/daily-metrics/2026-01-01", token, BODY)
    history = request("GET", "/daily-metrics?from=2026-01-01&to=2026-01-02&limit=1", token).json()
    assert history["total"] == 2 and len(history["items"]) == 1
    assert history["items"][0]["log_date"] == "2026-01-02"
    assert request("GET", "/daily-metrics?from=2026-01-01&to=2026-01-01", token).json()["total"] == 1
    assert request("GET", "/daily-metrics?offset=1", token).json()["items"][0]["log_date"] == "2026-01-01"
    other = register_and_login(auth_db[1](unique_email("metrics-other")))
    assert request("GET", path, other).status_code == 404
    assert request("DELETE", path, other).status_code == 404
    assert request("GET", "/daily-metrics", other).json()["items"] == []
    assert request("PUT", path, other, BODY).status_code == 200
    assert request("GET", path, token).json()["water_glasses"] == 0
    assert request("DELETE", path, token).status_code == 204
    assert request("GET", path, token).json()["error"]["code"] == "DAILY_METRICS_NOT_FOUND"
    assert request("DELETE", path, token).status_code == 404
    assert request("GET", path, other).status_code == 200


@pytest.mark.parametrize("field,value", [
    ("water_glasses", -1), ("water_glasses", 101), ("water_glasses", 1.5),
    ("water_glasses", True), ("water_glasses", "8"),
    ("fruit_veg_servings", -1), ("fruit_veg_servings", 101),
    ("fruit_veg_servings", "NaN"), ("fruit_veg_servings", True),
    ("sleep_hours", -1), ("sleep_hours", 24.1), ("sleep_hours", "Infinity"),
    ("sleep_hours", None), ("other", 1),
])
def test_daily_metrics_validation(tracking_user, field, value):
    _, token = tracking_user
    result = request("PUT", "/daily-metrics/2026-01-01", token, {**BODY, field: value})
    assert result.status_code == 422


def test_daily_metrics_auth_partial_put_and_dates(tracking_user):
    _, token = tracking_user
    path = "/daily-metrics/2026-01-01"
    for method, url, body in [("GET", path, None), ("GET", "/daily-metrics", None),
                              ("PUT", path, BODY), ("DELETE", path, None)]:
        assert request(method, url, body=body).status_code == 401
    assert request("PUT", path, token, {"water_glasses": 5}).status_code == 422
    assert request("PATCH", path, token, BODY).status_code == 405
    for query in ("from=2026-02-01&to=2026-01-01", "limit=0", "offset=-1", "from=invalid"):
        assert request("GET", "/daily-metrics?" + query, token).status_code == 422
    today = datetime.now(timezone.utc).date()
    for offset in (0, 1):
        assert request("PUT", f"/daily-metrics/{today + timedelta(days=offset)}", token, BODY).status_code == 200
    rejected = request("PUT", f"/daily-metrics/{today + timedelta(days=2)}", token, BODY)
    assert rejected.status_code == 422 and rejected.json()["error"]["code"] == "FUTURE_LOG_DATE"


def test_daily_metrics_database_constraints_export_and_account_cascade(tracking_user):
    db, token = tracking_user
    user_id = UUID(request("GET", "/auth/me", token).json()["id"])
    path = "/daily-metrics/2026-01-01"
    request("PUT", path, token, BODY)
    export = request("GET", "/users/me/export", token).json()
    assert export["records"]["daily_metrics"][0]["water_glasses"] == 8
    row = db.query(DailyMetrics).filter_by(user_id=user_id).one()
    for field, value in (("sleep_hours", 25), ("water_glasses", -1), ("fruit_veg_servings", 101)):
        setattr(row, field, value)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    duplicate = DailyMetrics(user_id=user_id, log_date=row.log_date, **BODY)
    db.add(duplicate)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert request("DELETE", "/users/me", token).status_code == 204
    assert db.scalar(select(func.count()).select_from(DailyMetrics).where(DailyMetrics.user_id == user_id)) == 0
