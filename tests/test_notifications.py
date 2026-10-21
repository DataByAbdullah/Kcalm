from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import register_and_login, unique_email


def test_notifications_sync_read_and_ownership(tracking_user, auth_db):
    _, token = tracking_user
    assert request("POST", "/notifications/sync", token).json()["created_count"] == 0
    request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": 80})
    assert request("POST", "/notifications/sync", token).json()["created_count"] == 1
    assert request("POST", "/notifications/sync", token).json()["created_count"] == 0
    inbox = request("GET", "/notifications?unread_only=true", token).json()
    assert inbox["unread_count"] == inbox["total"] == 1
    notification_id = inbox["items"][0]["id"]
    _, track = auth_db
    other = register_and_login(track(unique_email("notifications-other")))
    assert request("PATCH", f"/notifications/{notification_id}/read", other).status_code == 404
    assert request("GET", "/notifications", other).json()["total"] == 0
    read = request("PATCH", f"/notifications/{notification_id}/read", token)
    assert read.status_code == 200 and read.json()["read"] is True
    assert request("PATCH", f"/notifications/{notification_id}/read", token).json()["read_at"] == read.json()["read_at"]
    assert request("GET", "/notifications?unread_only=true", token).json()["total"] == 0
    assert request("GET", "/notifications").status_code == 401
    assert request("GET", "/notifications?limit=0", token).status_code == 422
