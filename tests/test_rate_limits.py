from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes.foods import get_usda_client
from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.core.exceptions import APIErrorException
from app.core.rate_limits import consume_rate_limit
from app.main import app
from app.models.rate_limit import RateLimitBucket
from app.schemas.ai import NaturalLanguageMealConstraintResponse
from tests.admin_helpers import promote_admin
from tests.test_auth import auth_db, login_user, register_user, unique_email
from tests.test_meal_plan_persistence import register_and_login
from tests.test_usda_integration import FakeUSDAClient, usda_db
from tests.test_weight_logs import request, tracking_user


@pytest.fixture
def small_limits():
    settings = get_settings().model_copy(update={
        f"rate_limit_{scope}_requests": 2
        for scope in ("register", "login", "forgot_password", "ai", "usda_import")
    })
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


def assert_limited(response, window):
    assert response.status_code == 429, response.text
    assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert 1 <= int(response.headers["Retry-After"]) <= window


@pytest.mark.parametrize("scope", ["register", "login", "forgot_password"])
def test_auth_routes_limit_each_client(auth_db, small_limits, monkeypatch, scope):
    _, track = auth_db
    email = track(unique_email("limited-auth"))
    if scope != "register":
        assert register_user(email).status_code == 201
    monkeypatch.setattr("app.services.auth_service.send_password_reset_email", lambda **kwargs: None)
    path = "/auth/" + scope.replace("_", "-")
    for _ in range(2):
        body = {"email": email, "password": "StrongPassword123"}
        if scope == "register":
            body["email"] = track(unique_email("limited-register"))
        response = request("POST", path, body=body)
        assert response.status_code == (201 if scope == "register" else 200), response.text
    blocked = request("POST", path, body={"email": email, "password": "StrongPassword123"})
    assert_limited(blocked, getattr(small_limits, f"rate_limit_{scope}_window_seconds"))
    assert request("GET", "/health").status_code == 200


def test_failed_login_attempts_also_consume_quota(auth_db, small_limits):
    _, track = auth_db
    email = track(unique_email("failed-login"))
    assert register_user(email).status_code == 201
    for _ in range(2):
        assert login_user(email, "wrong-password").status_code == 401
    assert_limited(login_user(email), 60)


def test_different_client_ips_have_separate_auth_buckets(auth_db, small_limits):
    from httpx import ASGITransport, AsyncClient
    from tests.test_auth import run_async

    async def check():
        for host in ("192.0.2.1", "192.0.2.2"):
            transport = ASGITransport(app=app, client=(host, 1234))
            async with AsyncClient(transport=transport, base_url="http://testserver") as client:
                for _ in range(2):
                    response = await client.post("/api/v1/auth/login", json={
                        "email": "missing@example.com", "password": "wrong-password",
                    })
                    assert response.status_code == 401
                response = await client.post("/api/v1/auth/login", json={
                    "email": "missing@example.com", "password": "wrong-password",
                })
                assert_limited(response, 60)
    run_async(check())


@pytest.fixture
def fake_ai(monkeypatch):
    constraints = NaturalLanguageMealConstraintResponse(
        requested_action="find_options", meal_type="lunch", max_total_time_minutes=None,
        required_tags=[], excluded_tags=[], excluded_recipe_ids=[], avoid_food_names=[],
        preference_food_names=[], unsupported_constraints=[], clarification_required=False,
        clarification_question=None, confidence=None, resolved_avoid_foods=[],
    )
    interpreted = SimpleNamespace(constraints=constraints)
    monkeypatch.setattr("app.api.routes.ai.interpret_natural_language_constraints", lambda **kwargs: interpreted)
    monkeypatch.setattr("app.api.routes.ai.preview_ai_meal_options", lambda **kwargs: (interpreted, None))


@pytest.mark.parametrize("path", ["/ai/constraints/interpret", "/ai/meal-options"])
def test_ai_routes_limit_by_authenticated_user(tracking_user, auth_db, small_limits, fake_ai, path):
    _, token = tracking_user
    for _ in range(2):
        assert request("POST", path, token, {"text": "Lunch"}).status_code == 200
    assert_limited(request("POST", path, token, {"text": "Lunch"}), 60)
    other = register_and_login(auth_db[1](unique_email("other-ai")))
    assert request("POST", path, other, {"text": "Lunch"}).status_code == 200
    assert request("GET", "/auth/me", token).status_code == 200
    assert request("GET", "/recipes", token).status_code == 200
    assert request("POST", path, body={"text": "Lunch"}).status_code == 401


def test_ai_endpoints_share_one_user_quota(tracking_user, small_limits, fake_ai):
    _, token = tracking_user
    for path in ("/ai/constraints/interpret", "/ai/meal-options"):
        assert request("POST", path, token, {"text": "Lunch"}).status_code == 200
    assert_limited(request("POST", "/ai/constraints/interpret", token, {"text": "Lunch"}), 60)


def test_usda_import_limits_each_admin(tracking_user, auth_db, usda_db, small_limits):
    _, token = tracking_user
    promote_admin(token)
    _, track_fdc_id, _ = usda_db
    fdc_id = track_fdc_id(988101)
    client = FakeUSDAClient()
    app.dependency_overrides[get_usda_client] = lambda: client
    path = f"/foods/usda/import/{fdc_id}"
    assert request("POST", path, token).status_code == 201
    assert request("POST", path, token).status_code == 200
    assert_limited(request("POST", path, token), 60)
    other = register_and_login(auth_db[1](unique_email("other-usda")))
    assert request("POST", path, other).status_code == 403
    promote_admin(other)
    assert request("POST", path, other).status_code == 200
    assert request("GET", "/foods/usda/search?q=banana", token).status_code == 200
    assert client.fetch_count == 1


def test_expired_bucket_resets_and_denials_do_not_extend_window(auth_db):
    db, _ = auth_db
    settings = get_settings().model_copy(update={"rate_limit_login_requests": 2})
    identity = "192.0.2.77"
    consume_rate_limit("login", identity, settings)
    consume_rate_limit("login", identity, settings)
    bucket = db.scalars(select(RateLimitBucket)).one()
    assert len(bucket.key_hash) == 64
    assert identity not in bucket.key_hash
    assert bucket.request_count == 2
    deadline = datetime.now(UTC) + timedelta(seconds=15)
    bucket.expires_at = deadline
    db.commit()
    with pytest.raises(APIErrorException) as error:
        consume_rate_limit("login", identity, settings)
    assert error.value.code == "RATE_LIMIT_EXCEEDED"
    assert 1 <= int(error.value.headers["Retry-After"]) <= 15
    db.refresh(bucket)
    assert bucket.expires_at == deadline
    assert bucket.request_count == 2
    bucket.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    consume_rate_limit("login", identity, settings)
    db.refresh(bucket)
    assert bucket.request_count == 1
    assert bucket.expires_at > datetime.now(UTC)
    assert len(db.scalars(select(RateLimitBucket)).all()) == 1


def test_concurrent_workers_cannot_exceed_bucket_limit(auth_db):
    settings = get_settings().model_copy(update={"rate_limit_login_requests": 3})
    identity = uuid4().hex

    def attempt(_):
        try:
            consume_rate_limit("login", identity, settings)
            return 200
        except APIErrorException as error:
            assert error.code == "RATE_LIMIT_EXCEEDED"
            return error.status_code

    with ThreadPoolExecutor(max_workers=6) as workers:
        results = list(workers.map(attempt, range(12)))
    assert results.count(200) == 3
    assert results.count(429) == 9
    with SessionLocal() as db:
        bucket = db.scalars(select(RateLimitBucket)).one()
        assert bucket.request_count == 3


def test_database_failure_does_not_disable_limiting(tracking_user, monkeypatch, fake_ai):
    _, token = tracking_user

    def unavailable():
        raise SQLAlchemyError("private connection details")

    monkeypatch.setattr("app.core.rate_limits.SessionLocal.begin", unavailable)
    response = request("POST", "/ai/meal-options", token, {"text": "Lunch"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"
    assert "private connection details" not in response.text


def test_rate_limit_defaults_and_environment_configuration(monkeypatch):
    settings = Settings(_env_file=None)
    for scope, limit, seconds in [
        ("register", 5, 60), ("login", 10, 60), ("forgot_password", 5, 300),
        ("ai", 30, 60), ("usda_import", 20, 60),
    ]:
        assert getattr(settings, f"rate_limit_{scope}_requests") == limit
        assert getattr(settings, f"rate_limit_{scope}_window_seconds") == seconds
        monkeypatch.setenv(f"RATE_LIMIT_{scope.upper()}_REQUESTS", "7")
        monkeypatch.setenv(f"RATE_LIMIT_{scope.upper()}_WINDOW_SECONDS", "45")
    configured = Settings(_env_file=None)
    assert configured.rate_limit_register_requests == configured.rate_limit_usda_import_requests == 7
    assert configured.rate_limit_ai_window_seconds == 45
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rate_limit_login_requests=0)
