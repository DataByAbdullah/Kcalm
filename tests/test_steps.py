from datetime import datetime, timedelta, timezone

import pytest

from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import register_and_login, unique_email


def test_steps_manual_history_update_and_isolation(tracking_user, auth_db):
    _, token = tracking_user
    result = request("PUT", "/steps/2026-01-01", token, {"steps": 4000})
    assert result.status_code == 200
    assert result.json()["source"] == "manual"
    request("PUT", "/steps/2026-01-01", token, {"steps": 8000})
    request("PUT", "/steps/2026-01-02", token, {"steps": 0})
    history = request("GET", "/steps?start_date=2026-01-01&end_date=2026-01-01", token).json()
    assert history["total"] == 1
    assert history["items"][0]["steps"] == 8000
    _, track = auth_db
    other = register_and_login(track(unique_email("steps-other")))
    assert request("GET", "/steps/2026-01-01", other).status_code == 404
    assert request("DELETE", "/steps/2026-01-01", other).status_code == 404
    assert request("DELETE", "/steps/2026-01-01", token).status_code == 204
    assert request("GET", "/steps/2026-01-01", token).status_code == 404


@pytest.mark.parametrize("value", [-1, 200001, 1.5, True, "42"])
def test_steps_reject_invalid_totals(tracking_user, value):
    _, token = tracking_user
    assert request("PUT", "/steps/2026-01-01", token, {"steps": value}).status_code == 422


def test_steps_auth_dates_and_pagination(tracking_user):
    _, token = tracking_user
    assert request("GET", "/steps").status_code == 401
    assert request("GET", "/steps?limit=0", token).status_code == 422
    assert request("GET", "/steps?start_date=2026-02-01&end_date=2026-01-01", token).status_code == 422
    utc_today = datetime.now(timezone.utc).date()
    for days_ahead in (0, 1):
        log_date = (utc_today + timedelta(days=days_ahead)).isoformat()
        assert request("PUT", f"/steps/{log_date}", token, {"steps": 100}).status_code == 200
    too_far = (utc_today + timedelta(days=2)).isoformat()
    rejected = request("PUT", f"/steps/{too_far}", token, {"steps": 100})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "FUTURE_LOG_DATE"
