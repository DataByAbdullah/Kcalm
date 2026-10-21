from tests.test_grocery_lists import grocery_db, create_week_and_grocery_list, patch_grocery_item
from tests.test_weekly_meal_plans import setup_foods, create_profile, register_and_login, unique_email


def test_grocery_detail_reports_real_completion_counts(grocery_db):
    db, track_email, track_recipe = grocery_db
    setup_foods(db)
    token = register_and_login(track_email(unique_email("grocery-progress")))
    create_profile(token)
    _, grocery, _ = create_week_and_grocery_list(db, token, track_recipe, "2026-01-05")
    assert grocery["item_count"] == len(grocery["items"])
    assert grocery["checked_item_count"] == 0
    assert grocery["completion_percent"] == 0
    response = patch_grocery_item(token, grocery["grocery_list_id"], grocery["items"][0]["id"], {"checked": True})
    assert response.status_code == 200
    assert response.json()["checked_item_count"] == 1
    assert response.json()["completion_percent"] == round(100 / len(grocery["items"]), 1)
