import smtplib

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import get_db
from app.main import app
from tests.test_auth import auth_db, login_user, register_user, unique_email
from tests.test_weight_logs import request, tracking_user


def test_registration_cannot_assign_admin_and_me_exposes_role(auth_db):
    db, track = auth_db
    email = track(unique_email("admin-escalation"))
    response = request("POST", "/auth/register", body={
        "email": email, "password": "StrongPassword123", "is_admin": True,
    })
    assert response.status_code == 201
    assert response.json()["is_admin"] is False
    from app.models.user import User
    assert db.query(User).filter_by(email=email).one().is_admin is False
    token = login_user(email).json()["access_token"]
    me = request("GET", "/auth/me", token)
    assert me.status_code == 200
    assert me.json()["is_admin"] is False
    assert set(me.json()) == {"id", "email", "full_name", "membership_tier", "is_active", "is_admin"}


def test_logout_revokes_access_and_refresh_and_allows_password_login(tracking_user):
    db, token = tracking_user
    email = request("GET", "/auth/me", token).json()["email"]
    tokens = login_user(email).json()
    response = request("POST", "/auth/logout", tokens["access_token"])
    assert response.status_code == 200
    assert response.json() == {"message": "Logged out successfully."}
    for access in (token, tokens["access_token"]):
        rejected = request("GET", "/auth/me", access)
        assert rejected.status_code == 401
        assert rejected.json()["error"]["code"] == "INVALID_TOKEN"
    refresh = request("POST", "/auth/refresh", body={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401
    assert refresh.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"
    fresh = login_user(email)
    assert fresh.status_code == 200
    assert request("GET", "/auth/me", fresh.json()["access_token"]).status_code == 200
    assert request("POST", "/auth/refresh", body={
        "refresh_token": fresh.json()["refresh_token"],
    }).status_code == 200


def test_logout_requires_authentication():
    assert request("POST", "/auth/logout").status_code == 401


def test_logout_database_failure_is_controlled_and_rolls_back(tracking_user, monkeypatch):
    db, token = tracking_user
    app.dependency_overrides[get_db] = lambda: db
    try:
        with monkeypatch.context() as patch:
            def fail_commit():
                raise SQLAlchemyError("private database details")
            patch.setattr(db, "commit", fail_commit)
            response = request("POST", "/auth/logout", token)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "LOGOUT_FAILED"
        assert "private database details" not in response.text
        assert request("GET", "/auth/me", token).status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("failure", [
    smtplib.SMTPException, OSError, ConnectionError, TimeoutError,
])
def test_password_reset_delivery_failure_stays_generic(auth_db, monkeypatch, caplog, failure):
    _, track = auth_db
    email = track(unique_email("smtp-failure"))
    assert register_user(email).status_code == 201
    captured = {}

    def fail_delivery(email, reset_token):
        captured["token"] = reset_token
        raise failure("private SMTP details and credentials")

    monkeypatch.setattr("app.services.auth_service.send_password_reset_email", fail_delivery)
    known = request("POST", "/auth/forgot-password", body={"email": email})
    unknown = request("POST", "/auth/forgot-password", body={"email": unique_email("unknown")})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json() == {
        "message": "If an account exists for this email, a password reset link has been sent.",
    }
    assert captured["token"] not in known.text + unknown.text + caplog.text
    assert "private SMTP" not in known.text + caplog.text
    assert email not in caplog.text
    assert "Password reset email delivery failed." in caplog.text


def test_password_reset_does_not_swallow_programming_errors(tracking_user, monkeypatch):
    _, token = tracking_user
    email = request("GET", "/auth/me", token).json()["email"]

    def bug(**kwargs):
        raise TypeError("programming bug")

    monkeypatch.setattr("app.services.auth_service.send_password_reset_email", bug)
    with pytest.raises(TypeError, match="programming bug"):
        request("POST", "/auth/forgot-password", body={"email": email})
