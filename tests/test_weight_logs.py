from datetime import datetime, timedelta, timezone

import pytest

from tests.test_meal_plan_persistence import api_request, auth_headers, create_profile, register_and_login, run_async, unique_email
from tests.test_auth import auth_db


@pytest.fixture
def tracking_user(auth_db):
    db, track = auth_db
    token = register_and_login(track(unique_email("tracking")))
    return db, token


def request(method, path, token=None, body=None):
    kwargs = {"headers": auth_headers(token)} if token else {}
    if body is not None:
        kwargs["json"] = body
    return run_async(api_request(method, "/api/v1" + path, **kwargs))


def test_weight_crud_progress_and_ownership(tracking_user, auth_db):
    _, token = tracking_user
    create_profile(token, target_weight_kg=75)
    assert request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": 85}).status_code == 200
    assert request("PUT", "/weight-logs/2026-02-01", token, {"weight_kg": 80}).status_code == 200
    result = request("GET", "/weight-logs", token).json()
    assert result["total"] == 2
    assert result["progress"]["progress_percent"] == 50
    assert result["progress"]["remaining_kg"] == 5
    assert request("GET", "/users/profile", token).json()["weight_kg"] == 82
    assert request("PUT", "/weight-logs/2026-02-01", token, {"weight_kg": 79}).status_code == 200
    assert request("GET", "/weight-logs?limit=1", token).json()["total"] == 2
    _, track = auth_db
    other = register_and_login(track(unique_email("other")))
    assert request("DELETE", "/weight-logs/2026-02-01", other).status_code == 404
    assert request("GET", "/weight-logs", other).json()["items"] == []
    assert request("DELETE", "/weight-logs/2026-02-01", token).status_code == 204


def test_gain_progress_and_missing_data(tracking_user):
    _, token = tracking_user
    empty = request("GET", "/weight-logs", token).json()
    assert empty["progress"]["current_weight_kg"] is None
    assert empty["progress"]["progress_percent"] is None
    create_profile(token, target_weight_kg=90)
    request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": 80})
    request("PUT", "/weight-logs/2026-02-01", token, {"weight_kg": 85})
    assert request("GET", "/weight-logs", token).json()["progress"]["progress_percent"] == 50


@pytest.mark.parametrize("value", [0, -1, 501, "NaN", "Infinity"])
def test_weight_validation(tracking_user, value):
    _, token = tracking_user
    assert request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": value}).status_code == 422


def test_weight_dates_and_auth(tracking_user):
    _, token = tracking_user
    utc_today = datetime.now(timezone.utc).date()
    for days_ahead in (0, 1):
        log_date = (utc_today + timedelta(days=days_ahead)).isoformat()
        assert request("PUT", f"/weight-logs/{log_date}", token, {"weight_kg": 80}).status_code == 200
    too_far = (utc_today + timedelta(days=2)).isoformat()
    rejected = request("PUT", f"/weight-logs/{too_far}", token, {"weight_kg": 80})
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "FUTURE_LOG_DATE"
    assert request("GET", "/weight-logs?start_date=2026-02-01&end_date=2026-01-01", token).status_code == 422
    assert request("GET", "/weight-logs").status_code == 401


@pytest.mark.parametrize(("start", "current", "target", "percent", "remaining"), [
    (85, 70, 75, 100, 0), (75, 95, 90, 100, 0), (85, 90, 75, 0, 15), (80, 80, 80, 100, 0),
])
def test_weight_progress_handles_overshoot_and_maintenance(tracking_user, start, current, target, percent, remaining):
    _, token = tracking_user
    create_profile(token, target_weight_kg=target)
    request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": start})
    request("PUT", "/weight-logs/2026-01-02", token, {"weight_kg": current})
    progress = request("GET", "/weight-logs", token).json()["progress"]
    assert progress["progress_percent"] == percent
    assert progress["remaining_kg"] == remaining
