from app.core.config import Settings, get_settings
from app.main import app
from tests.test_auth import auth_db
from tests.test_weight_logs import request, tracking_user


def test_integration_catalog_is_honest_and_contains_no_credentials(tracking_user):
    _, token = tracking_user
    settings = Settings(_env_file=None, openai_api_key="secret-test-key", usda_api_key="", smtp_host="", smtp_from_email="")
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = request("GET", "/integrations", token)
        assert response.status_code == 200
        items = {item["code"]: item for item in response.json()["items"]}
        assert items["openai"]["status"] == "configured"
        assert items["usda"]["status"] == "not_configured"
        assert items["wearable_sync"]["status"] == "not_implemented"
        assert all(item["connection_verified"] is False for item in items.values())
        assert "secret-test-key" not in response.text
        assert request("GET", "/integrations/openai", token).json() == items["openai"]
        assert request("GET", "/integrations/unknown", token).status_code == 404
        assert request("GET", "/integrations").status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)
