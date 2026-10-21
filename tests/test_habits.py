from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user
from tests.test_meal_plan_persistence import register_and_login, unique_email


def test_habit_lifecycle_and_history(tracking_user):
    _, token = tracking_user
    created = request("POST", "/habits", token, {"name": " Walk daily ", "start_date": "2026-01-02"})
    assert created.status_code == 201
    habit_id = created.json()["id"]
    path = f"/habits/{habit_id}"
    assert request("PUT", path + "/completions/2026-01-01", token, {"completed": True}).status_code == 422
    for _ in range(2):
        assert request("PUT", path + "/completions/2026-01-02", token, {"completed": True}).status_code == 200
    daily = request("GET", "/habits?date=2026-01-02", token).json()
    assert daily["items"][0]["completed"] is True
    history = request("GET", path + "/history?start_date=2026-01-01&end_date=2026-01-03", token).json()
    assert history["items"] == [{"date": "2026-01-02", "completed": True}, {"date": "2026-01-03", "completed": False}]
    assert request("PUT", path + "/completions/2026-01-02", token, {"completed": False}).status_code == 200
    assert request("PATCH", path, token, {"name": "Evening walk", "active": False}).status_code == 200
    assert request("PUT", path + "/completions/2026-01-02", token, {"completed": True}).status_code == 409
    assert request("DELETE", path, token).status_code == 204
    assert request("GET", path + "/history", token).status_code == 404


def test_habit_ownership_and_auth(tracking_user, auth_db):
    _, token = tracking_user
    habit_id = request("POST", "/habits", token, {"name": "Stretch"}).json()["id"]
    _, track = auth_db
    other = register_and_login(track(unique_email("habit-other")))
    assert request("GET", "/habits", other).json()["items"] == []
    assert request("PATCH", f"/habits/{habit_id}", other, {"active": False}).status_code == 404
    assert request("DELETE", f"/habits/{habit_id}", other).status_code == 404
    assert request("GET", f"/habits/{habit_id}/history", other).status_code == 404
    assert request("GET", "/habits").status_code == 401


def test_habit_validation(tracking_user):
    _, token = tracking_user
    assert request("POST", "/habits", token, {"name": "   "}).status_code == 422
    habit_id = request("POST", "/habits", token, {"name": "Stretch"}).json()["id"]
    for body in ({"name": None}, {"active": None}, {}, {"name": "   "}):
        assert request("PATCH", f"/habits/{habit_id}", token, body).status_code == 422
    assert request("GET", f"/habits/{habit_id}/history?start_date=2020-01-01&end_date=2026-01-01", token).status_code == 422
