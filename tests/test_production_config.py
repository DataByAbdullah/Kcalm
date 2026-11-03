import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import DEFAULT_JWT_SECRET, Settings
from app.main import create_app
from tests.test_auth import run_async


@pytest.mark.parametrize("environment", ["production", "PRODUCTION", "prod", "PrOd"])
def test_production_rejects_default_jwt_secret(monkeypatch, environment):
    settings = Settings(_env_file=None, app_env=environment, jwt_secret=DEFAULT_JWT_SECRET)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="JWT_SECRET must be changed") as error:
        create_app()
    assert DEFAULT_JWT_SECRET not in str(error.value)


@pytest.mark.parametrize("environment,secret,expected", [
    ("development", DEFAULT_JWT_SECRET, 200),
    ("test", DEFAULT_JWT_SECRET, 200),
    ("production", "separate-test-secret-that-is-at-least-32-bytes", 404),
    ("PROD", "another-test-secret-that-is-at-least-32-bytes", 404),
])
def test_documentation_visibility(monkeypatch, environment, secret, expected):
    settings = Settings(_env_file=None, app_env=environment, jwt_secret=secret)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    application = create_app()

    async def check():
        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as client:
            for path in ("/docs", "/redoc", "/openapi.json"):
                assert (await client.get(path)).status_code == expected
    run_async(check())
