from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import create_profile, register_and_login, unique_email


def test_export_is_versioned_and_contains_only_owned_non_secret_data(tracking_user, auth_db):
    _, token = tracking_user
    create_profile(token, target_weight_kg=75)
    request("PUT", "/weight-logs/2026-01-01", token, {"weight_kg": 80})
    habit_id = request("POST", "/habits", token, {"name": "Walk", "start_date": "2026-01-01"}).json()["id"]
    request("PUT", f"/habits/{habit_id}/completions/2026-01-01", token, {"completed": True})
    response = request("GET", "/users/me/export", token)
    assert response.status_code == 200, response.text
    export = response.json()
    assert export["schema_version"] == "1.0"
    assert export["records"]["weight_logs"][0]["weight_kg"] == 80
    assert export["records"]["habit_completions"][0]["habit_id"] == habit_id
    assert export["records"]["user_profiles"][0]["target_weight_kg"] == 75
    assert "attachment" in response.headers["content-disposition"]
    for secret in ("password_hash", "token_version", "access_token", "refresh_token"):
        assert secret not in response.text
    _, track = auth_db
    other = register_and_login(track(unique_email("export-other")))
    other_export = request("GET", "/users/me/export", other).json()
    assert all(not rows for rows in other_export["records"].values())
    assert request("GET", "/users/me/export").status_code == 401
