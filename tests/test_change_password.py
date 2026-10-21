from tests.test_auth import auth_db, login_user
from tests.test_weight_logs import request, tracking_user


def test_password_change_revokes_sessions_and_refresh_tokens(tracking_user):
    _, token = tracking_user
    email = request("GET", "/auth/me", token).json()["email"]
    refresh = login_user(email).json()["refresh_token"]
    result = request("POST", "/auth/change-password", token,
                     {"current_password": "StrongPassword123", "new_password": "AnotherStrongPassword456"})
    assert result.status_code == 200
    assert request("GET", "/auth/me", token).status_code == 401
    assert request("POST", "/auth/refresh", body={"refresh_token": refresh}).status_code == 401
    assert login_user(email).status_code == 401
    new_login = login_user(email, "AnotherStrongPassword456")
    assert new_login.status_code == 200
    assert request("GET", "/auth/me", new_login.json()["access_token"]).status_code == 200
    assert request("POST", "/auth/refresh", body={"refresh_token": new_login.json()["refresh_token"]}).status_code == 200


def test_password_change_validates_current_password_and_shape(tracking_user):
    _, token = tracking_user
    assert request("POST", "/auth/change-password", token, {"current_password": "Wrong", "new_password": "AnotherPassword123"}).status_code == 400
    assert request("POST", "/auth/change-password", token, {"current_password": "StrongPassword123", "new_password": "StrongPassword123"}).status_code == 422
    assert request("POST", "/auth/change-password", token, {"current_password": "StrongPassword123", "new_password": "short"}).status_code == 422
    assert request("POST", "/auth/change-password", body={"current_password": "StrongPassword123", "new_password": "AnotherPassword123"}).status_code == 401
    assert request("GET", "/auth/me", token).status_code == 200
