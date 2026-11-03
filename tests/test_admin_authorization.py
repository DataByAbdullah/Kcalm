import pytest

from app.api.routes.foods import get_usda_client
from app.main import app
from tests.admin_helpers import promote_admin
from tests.test_auth import auth_db
from tests.test_meal_plan_persistence import create_profile
from tests.test_recipes import recipe_db, recipe_payload
from tests.test_usda_integration import FakeUSDAClient, usda_db
from tests.test_weight_logs import request, tracking_user


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/recipes", {}),
    ("PATCH", "/recipes/00000000-0000-0000-0000-000000000001", {}),
    ("DELETE", "/recipes/00000000-0000-0000-0000-000000000001", None),
    ("POST", "/foods/usda/import/234567", None),
])
def test_normal_user_cannot_mutate_catalog(tracking_user, method, path, body):
    _, token = tracking_user
    response = request(method, path, token, body)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_admin_recipe_crud_and_normal_user_reads(tracking_user, recipe_db):
    _, token = tracking_user
    db, track_recipe, _, track_email = recipe_db
    from app.services.food_seed_service import seed_development_foods
    seed_development_foods(db)
    promote_admin(token)
    assert request("GET", "/auth/me", token).json()["is_admin"] is True
    created = request("POST", "/recipes", token, recipe_payload(db))
    assert created.status_code == 201, created.text
    recipe_id = track_recipe(created.json()["id"])
    changed = request("PATCH", f"/recipes/{recipe_id}", token, {"description": "Admin updated."})
    assert changed.status_code == 200
    assert changed.json()["description"] == "Admin updated."

    from tests.test_meal_plan_persistence import register_and_login, unique_email
    normal = register_and_login(track_email(unique_email("normal-reader")))
    create_profile(normal)
    assert request("GET", "/auth/me", normal).json()["is_admin"] is False
    assert request("GET", "/recipes", normal).status_code == 200
    assert request("GET", f"/recipes/{recipe_id}", normal).status_code == 200
    assert request("POST", "/recipes/candidates/preview", normal, {}).status_code == 200
    assert request("DELETE", f"/recipes/{recipe_id}", token).status_code == 204


def test_usda_search_for_normal_user_and_import_for_admin(tracking_user, usda_db):
    _, token = tracking_user
    _, track_fdc_id, _ = usda_db
    fdc_id = track_fdc_id(988100)
    client = FakeUSDAClient()
    app.dependency_overrides[get_usda_client] = lambda: client
    assert request("GET", "/foods/usda/search?q=banana", token).status_code == 200
    rejected = request("POST", f"/foods/usda/import/{fdc_id}", token)
    assert rejected.status_code == 403
    assert client.fetch_count == 0
    promote_admin(token)
    assert request("POST", f"/foods/usda/import/{fdc_id}", token).status_code == 201
    assert client.fetch_count == 1
