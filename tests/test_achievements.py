from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import register_and_login, unique_email


def test_achievements_are_derived_from_owned_data(tracking_user, auth_db):
    _, token = tracking_user
    empty = request("GET", "/achievements", token).json()["items"]
    assert all(item["current"] == 0 and not item["unlocked"] for item in empty)
    request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": 80})
    request("PUT", "/steps/2026-01-01", token, {"steps": 10000})
    habit_id = request("POST", "/habits", token, {"name": "Walk", "start_date": "2026-01-01"}).json()["id"]
    request("PUT", f"/habits/{habit_id}/completions/2026-01-01", token, {"completed": True})
    result = {item["code"]: item for item in request("GET", "/achievements", token).json()["items"]}
    assert result["first_weight"]["unlocked"] is True
    assert result["steps_10000"]["current"] == 10000
    assert result["habit_completions_7"]["current"] == 1
    request("DELETE", "/weight-logs/2026-01-01", token)
    assert not request("GET", "/achievements", token).json()["items"][0]["unlocked"]
    _, track = auth_db
    other = register_and_login(track(unique_email("achievement-other")))
    assert all(item["current"] == 0 for item in request("GET", "/achievements", other).json()["items"])
    assert request("GET", "/achievements").status_code == 401
