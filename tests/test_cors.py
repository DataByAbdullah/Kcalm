import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


FRONTEND_ORIGINS = ["https://kcalm-app.vercel.app", "http://localhost:3000"]


@pytest.fixture(params=["development", "production"])
def cors_app(monkeypatch, request):
    settings = Settings(
        _env_file=None,
        app_env=request.param,
        jwt_secret="cors-test-secret-that-is-at-least-32-bytes",
        cors_origins=FRONTEND_ORIGINS,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    return create_app()


def request(application, method, path="/api/v1/health", **kwargs):
    async def send():
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)
    return asyncio.run(send())


@pytest.mark.parametrize("origin", FRONTEND_ORIGINS)
def test_allowed_frontend_origin_receives_credentialed_cors_headers(cors_app, origin):
    response = request(cors_app, "GET", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert "Origin" in response.headers["Vary"]
    assert response.headers["Access-Control-Expose-Headers"] == "Retry-After"


@pytest.mark.parametrize("origin", [
    "https://unknown.example", "https://kcalm-app.vercel.app.attacker.example",
])
def test_unknown_origin_does_not_receive_cors_permission(cors_app, origin):
    response = request(cors_app, "GET", headers={"Origin": origin})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


@pytest.mark.parametrize("origin", FRONTEND_ORIGINS)
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_options_preflight_allows_frontend_methods_and_headers(cors_app, origin, method):
    response = request(cors_app, "OPTIONS", "/api/v1/auth/login", headers={
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "authorization,content-type,x-request-id",
    })
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert method in response.headers["Access-Control-Allow-Methods"].split(", ")
    assert response.headers["Access-Control-Allow-Headers"] == "authorization,content-type,x-request-id"


def test_options_preflight_rejects_unknown_origin(cors_app):
    response = request(cors_app, "OPTIONS", headers={
        "Origin": "https://unknown.example",
        "Access-Control-Request-Method": "GET",
    })
    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_headers_are_present_on_authentication_errors(cors_app):
    origin = FRONTEND_ORIGINS[0]
    response = request(cors_app, "GET", "/api/v1/auth/me", headers={"Origin": origin})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert response.headers["Access-Control-Allow-Credentials"] == "true"


def test_requests_without_origin_keep_existing_behavior(cors_app):
    response = request(cors_app, "GET")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "kcalm-api"}
    assert "Access-Control-Allow-Origin" not in response.headers


def test_cors_origins_defaults_and_environment_override(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings(_env_file=None).cors_origins == FRONTEND_ORIGINS
    configured_origin = "https://frontend.example"
    monkeypatch.setenv("CORS_ORIGINS", json.dumps([configured_origin]))
    settings = Settings(_env_file=None)
    assert settings.cors_origins == [configured_origin]
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    application = create_app()
    response = request(application, "GET", headers={"Origin": configured_origin})
    assert response.headers["Access-Control-Allow-Origin"] == configured_origin
    for previous_origin in FRONTEND_ORIGINS:
        response = request(application, "GET", headers={"Origin": previous_origin})
        assert "Access-Control-Allow-Origin" not in response.headers


def test_wildcard_cors_origin_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["*"]')
    with pytest.raises(ValidationError, match="wildcard origins are forbidden"):
        Settings(_env_file=None)
