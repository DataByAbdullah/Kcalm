import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from ortools.sat.python import cp_model
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.main import app
from app.meal_planning.scaling import scale_amount, scaled_tolerance_bounds, unscale_amount
from app.meal_planning.solver import (
    DailyPlanSolverInput,
    DailyPlanSolverResult,
    MealSlot,
    MealSolverInputError,
    SolverConfig,
    SolverMicronutrientTarget,
    SolverNutritionTargets,
    SolverStatus,
    ToleranceStatus,
    default_meal_slots,
    map_cp_solver_status,
    solve_daily_plan,
)
from app.models.recipe import Recipe
from app.models.user import User
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE
from app.schemas.meal_plan import DailySolverPreviewRequest
from app.seed_data.recipes import DEV_RECIPE_SEED_SOURCE
from app.services.food_seed_service import seed_development_foods
from app.services.recipe_candidate_service import (
    CandidateFilterResult,
    CandidateNutrient,
    RecipeCandidate,
)
from app.services.recipe_seed_service import seed_development_recipes


def run_async(coro):
    return asyncio.run(coro)


async def api_request(method: str, url: str, **kwargs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, url, **kwargs)


@pytest.fixture
def require_solver_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {
                "users",
                "user_profiles",
                "foods",
                "food_nutrients",
                "recipes",
                "recipe_ingredients",
                "recipe_tags",
                "recipe_tag_links",
                "recipe_equipment",
                "recipe_nutrients",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("meal solver tables are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def solver_db(require_solver_tables):
    db = SessionLocal()
    created_emails: list[str] = []
    created_recipe_ids: list[UUID] = []

    def track_email(email: str) -> str:
        normalized_email = email.strip().lower()
        created_emails.append(normalized_email)
        return normalized_email

    def track_recipe(recipe_id: str | UUID) -> UUID:
        parsed_id = UUID(str(recipe_id))
        created_recipe_ids.append(parsed_id)
        return parsed_id

    yield db, track_email, track_recipe

    for recipe_id in created_recipe_ids:
        recipe = db.get(Recipe, recipe_id)
        if recipe is not None:
            db.delete(recipe)
    db.commit()

    for email in created_emails:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is not None:
            db.delete(user)
    db.commit()
    db.close()


def unique_email(prefix: str = "solver") -> str:
    return f"{prefix}-{uuid4().hex}@example.com"


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def register_and_login(email: str) -> str:
    register_response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/register",
            json={"email": email, "password": "StrongPassword123"},
        )
    )
    assert register_response.status_code == 201

    login_response = run_async(
        api_request(
            "POST",
            "/api/v1/auth/login",
            json={"email": email, "password": "StrongPassword123"},
        )
    )
    assert login_response.status_code == 200
    return login_response.json()["access_token"]


def create_profile(token: str, **overrides) -> None:
    payload = {
        "age": 29,
        "sex": "male",
        "height_cm": 178,
        "weight_kg": 82,
        "activity_level": "moderate",
        "goal": "fat_loss",
        "target_rate": 0.5,
        "max_cooking_minutes": 60,
        "meals_per_day": 4,
        "allergies": [],
        "dietary_restrictions": [],
        "preferred_foods": [],
        "disliked_foods": [],
        "equipment": ["stovetop", "oven", "blender"],
    }
    payload.update(overrides)
    response = run_async(
        api_request(
            "POST",
            "/api/v1/users/profile",
            headers=auth_headers(token),
            json=payload,
        )
    )
    assert response.status_code == 201, response.text


def solve_preview(token: str, body: dict | None = None):
    return run_async(
        api_request(
            "POST",
            "/api/v1/meal-plans/solve/preview",
            headers=auth_headers(token),
            json=body or {},
        )
    )


def nutrient_amounts(**overrides) -> dict[str, float]:
    amounts = {
        "calories": 100,
        "protein": 10,
        "carbohydrates": 10,
        "fat": 5,
        "fiber": 2,
        "calcium": 100,
        "iron": 2,
        "magnesium": 50,
        "potassium": 200,
        "sodium": 100,
        "vitamin_a": 100,
        "vitamin_c": 20,
        "vitamin_d": 2,
        "vitamin_b12": 1,
        "folate": 100,
    }
    amounts.update(overrides)
    return amounts


def candidate(
    name: str,
    meal_tags: list[str],
    nutrition: dict[str, float],
    complete: bool = True,
) -> RecipeCandidate:
    nutrients = [
        CandidateNutrient(
            code=code,
            name=definition.name,
            amount=nutrition[code],
            unit=definition.unit,
            complete=complete,
            missing_ingredient_count=0 if complete else 1,
        )
        for code, definition in RECIPE_NUTRIENT_DEFINITION_BY_CODE.items()
        if code in nutrition
    ]
    return RecipeCandidate(
        recipe_id=uuid4(),
        name=name,
        servings=1.0,
        total_time_minutes=10,
        meal_tags=meal_tags,
        tags=meal_tags,
        required_equipment=[],
        total_nutrition=nutrients,
        per_serving_nutrition=nutrients,
        nutrition_complete=complete,
        missing_nutrient_codes=[] if complete else ["protein"],
        preference_match_count=0,
        matched_preference_food_names=[],
        matched_preference_tags=[],
    )


def targets(
    calories: float = 600,
    protein: float = 60,
    carbohydrates: float = 60,
    fat: float = 15,
    fiber: float = 8,
    calcium: float = 600,
) -> SolverNutritionTargets:
    return SolverNutritionTargets(
        calories=calories,
        protein_g=protein,
        carbohydrates_g=carbohydrates,
        fat_g=fat,
        micronutrients=[
            SolverMicronutrientTarget(
                code="fiber",
                name="Fiber",
                target=fiber,
                unit="g",
                minimum_target=fiber,
                upper_limit=None,
                upper_limit_type=None,
            ),
            SolverMicronutrientTarget(
                code="calcium",
                name="Calcium",
                target=calcium,
                unit="mg",
                minimum_target=calcium,
                upper_limit=2500,
                upper_limit_type="UL",
            ),
        ],
    )


def test_integer_scaling_accuracy() -> None:
    assert scale_amount(1.2345) == 1235
    assert scale_amount(1.2344) == 1234
    assert unscale_amount(1235) == pytest.approx(1.235)
    assert scaled_tolerance_bounds(2000, 0.05) == (1_900_000, 2_100_000)


def test_solver_assigns_required_meal_slots_and_totals() -> None:
    breakfast = candidate("Breakfast", ["breakfast"], nutrient_amounts(calories=100, protein=10, carbohydrates=10, fat=5, fiber=2, calcium=100))
    lunch = candidate("Lunch", ["lunch"], nutrient_amounts(calories=200, protein=20, carbohydrates=20, fat=5, fiber=3, calcium=200))
    dinner = candidate("Dinner", ["dinner"], nutrient_amounts(calories=300, protein=30, carbohydrates=30, fat=5, fiber=4, calcium=300))

    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=[breakfast, lunch, dinner],
            targets=targets(),
            meal_slots=default_meal_slots(),
        )
    )

    assert result.status == SolverStatus.OPTIMAL
    assert [meal.meal_type for meal in result.meals] == ["breakfast", "lunch", "dinner"]
    assert result.daily_totals["calories"] == pytest.approx(600)
    assert result.daily_totals["protein"] == pytest.approx(60)
    assert result.daily_totals["carbohydrates"] == pytest.approx(60)
    assert result.daily_totals["fat"] == pytest.approx(15)
    assert result.daily_totals["fiber"] == pytest.approx(9)
    assert result.daily_totals["calcium"] == pytest.approx(600)


def test_optional_snack_is_selected_when_it_improves_nutrition() -> None:
    candidates = [
        candidate("Breakfast", ["breakfast"], nutrient_amounts(calories=100, protein=10, carbohydrates=10, fat=5, fiber=2, calcium=100)),
        candidate("Lunch", ["lunch"], nutrient_amounts(calories=200, protein=20, carbohydrates=20, fat=5, fiber=3, calcium=200)),
        candidate("Dinner", ["dinner"], nutrient_amounts(calories=300, protein=30, carbohydrates=30, fat=5, fiber=4, calcium=300)),
        candidate("Snack", ["snack"], nutrient_amounts(calories=100, protein=10, carbohydrates=10, fat=5, fiber=1, calcium=100)),
    ]

    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=candidates,
            targets=targets(calories=700, protein=70, carbohydrates=70, fat=20, fiber=10, calcium=700),
            meal_slots=default_meal_slots(),
        )
    )

    assert [meal.meal_type for meal in result.meals] == ["breakfast", "lunch", "dinner", "snack"]
    assert result.daily_totals["calories"] == pytest.approx(700)


def test_same_recipe_cannot_fill_multiple_slots() -> None:
    flexible = candidate("All Day", ["breakfast", "lunch", "dinner"], nutrient_amounts(calories=200, protein=20, carbohydrates=20))
    lunch = candidate("Lunch", ["lunch"], nutrient_amounts(calories=200, protein=20, carbohydrates=20))
    dinner = candidate("Dinner", ["dinner"], nutrient_amounts(calories=200, protein=20, carbohydrates=20))

    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=[flexible, lunch, dinner],
            targets=targets(calories=600, protein=60, carbohydrates=60, fat=15),
            meal_slots=[MealSlot("breakfast"), MealSlot("lunch"), MealSlot("dinner")],
        )
    )

    recipe_ids = [meal.recipe_id for meal in result.meals]
    assert result.status == SolverStatus.OPTIMAL
    assert len(recipe_ids) == len(set(recipe_ids))


def test_solver_selects_closer_nutrition_combination() -> None:
    breakfast = candidate("Breakfast", ["breakfast"], nutrient_amounts(calories=100, protein=10, carbohydrates=10, fat=5))
    lunch_low = candidate("Low Lunch", ["lunch"], nutrient_amounts(calories=100, protein=5, carbohydrates=5, fat=2))
    lunch_close = candidate("Close Lunch", ["lunch"], nutrient_amounts(calories=200, protein=20, carbohydrates=20, fat=5))
    dinner = candidate("Dinner", ["dinner"], nutrient_amounts(calories=300, protein=30, carbohydrates=30, fat=5))

    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=[breakfast, lunch_low, lunch_close, dinner],
            targets=targets(calories=600, protein=60, carbohydrates=60, fat=15),
            meal_slots=[MealSlot("breakfast"), MealSlot("lunch"), MealSlot("dinner")],
        )
    )

    selected_names = {meal.recipe_name for meal in result.meals}
    assert "Close Lunch" in selected_names
    assert "Low Lunch" not in selected_names


def test_solver_optimizes_open_slot_against_locked_nutrition() -> None:
    low_lunch = candidate(
        "Low Lunch",
        ["lunch"],
        nutrient_amounts(calories=200, protein=10, carbohydrates=20, fat=5, fiber=2, calcium=100),
    )
    close_lunch = candidate(
        "Close Lunch",
        ["lunch"],
        nutrient_amounts(calories=500, protein=40, carbohydrates=40, fat=10, fiber=6, calcium=500),
    )

    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=[low_lunch, close_lunch],
            targets=targets(calories=1000, protein=80, carbohydrates=80, fat=25, fiber=14, calcium=900),
            meal_slots=[MealSlot("lunch")],
            locked_nutrition={
                "calories": 500,
                "protein": 40,
                "carbohydrates": 40,
                "fat": 15,
                "fiber": 8,
                "calcium": 400,
            },
        )
    )

    assert result.status == SolverStatus.OPTIMAL
    assert result.meals[0].recipe_name == "Close Lunch"
    assert result.daily_totals["calories"] == pytest.approx(1000)
    assert result.daily_totals["protein"] == pytest.approx(80)
    assert result.daily_totals["calcium"] == pytest.approx(900)


def test_tolerance_and_micronutrient_coverage_metadata() -> None:
    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=[
                candidate("Breakfast", ["breakfast"], nutrient_amounts(calories=100, protein=10, carbohydrates=10, fat=5, fiber=1, calcium=100)),
                candidate("Lunch", ["lunch"], nutrient_amounts(calories=200, protein=20, carbohydrates=20, fat=5, fiber=2, calcium=200)),
                candidate("Dinner", ["dinner"], nutrient_amounts(calories=300, protein=30, carbohydrates=30, fat=5, fiber=2, calcium=200)),
            ],
            targets=targets(calories=1000, protein=60, carbohydrates=60, fat=15, fiber=10, calcium=1000),
            meal_slots=[MealSlot("breakfast"), MealSlot("lunch"), MealSlot("dinner")],
        )
    )

    deviations = {item.nutrient_code: item for item in result.deviations}
    coverage = {item.nutrient_code: item for item in result.micronutrient_coverage}
    assert deviations["calories"].status == ToleranceStatus.BELOW
    assert deviations["protein"].status == ToleranceStatus.WITHIN
    assert coverage["calcium"].coverage_percent == pytest.approx(50.0)
    assert coverage["calcium"].met is False
    assert result.within_preferred_tolerance is False


def test_invalid_targets_raise_controlled_solver_input_error() -> None:
    with pytest.raises(MealSolverInputError):
        solve_daily_plan(
            DailyPlanSolverInput(
                candidates=[],
                targets=targets(calories=0),
                meal_slots=[MealSlot("breakfast")],
            )
        )


def test_no_candidates_returns_infeasible_result() -> None:
    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=[],
            targets=targets(),
            meal_slots=[MealSlot("breakfast")],
        )
    )

    assert result.status == SolverStatus.INFEASIBLE
    assert result.infeasibility_reasons == ["no_eligible_candidates"]


def test_missing_meal_slot_candidate_returns_infeasible_result() -> None:
    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=[
                candidate("Breakfast", ["breakfast"], nutrient_amounts()),
                candidate("Lunch", ["lunch"], nutrient_amounts()),
            ],
            targets=targets(),
            meal_slots=[MealSlot("breakfast"), MealSlot("lunch"), MealSlot("dinner")],
        )
    )

    assert result.status == SolverStatus.INFEASIBLE
    assert "missing_meal_slot_candidate:dinner" in result.infeasibility_reasons


def test_infeasible_solver_assignment_is_controlled() -> None:
    one_recipe = candidate("Flexible", ["breakfast", "lunch", "dinner"], nutrient_amounts())

    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=[one_recipe],
            targets=targets(),
            meal_slots=[MealSlot("breakfast"), MealSlot("lunch")],
        )
    )

    assert result.status == SolverStatus.INFEASIBLE
    assert result.infeasibility_reasons == ["solver_no_structurally_valid_assignment"]


def test_malformed_candidate_nutrition_is_handled_safely() -> None:
    malformed = candidate(
        "Malformed",
        ["breakfast"],
        nutrient_amounts(),
        complete=False,
    )

    result = solve_daily_plan(
        DailyPlanSolverInput(
            candidates=[malformed],
            targets=targets(),
            meal_slots=[MealSlot("breakfast")],
        )
    )

    assert result.status == SolverStatus.INFEASIBLE
    assert "all_candidate_nutrition_malformed" in result.infeasibility_reasons


def test_solver_status_mapping_supports_feasible_not_optimal() -> None:
    assert map_cp_solver_status(cp_model.OPTIMAL) == SolverStatus.OPTIMAL
    assert map_cp_solver_status(cp_model.FEASIBLE) == SolverStatus.FEASIBLE
    assert map_cp_solver_status(cp_model.UNKNOWN) == SolverStatus.INFEASIBLE


def test_preview_service_uses_candidate_filtering(monkeypatch) -> None:
    from app.services import meal_solver_service

    calls = {}

    def fake_get_profile(db, user):
        return SimpleNamespace(
            age=29,
            sex="male",
            height_cm=178,
            weight_kg=82,
            activity_level="moderate",
            goal="fat_loss",
            target_rate=0.5,
        )

    def fake_get_recipe_candidates(**kwargs):
        calls["candidate_kwargs"] = kwargs
        return CandidateFilterResult(
            candidates=[],
            total_eligible=0,
            exclusion_summary={},
            excluded=[],
            allergy_filtering_supported=False,
            unsupported_dietary_restrictions=[],
            filter_order=[],
        )

    sentinel = object()
    monkeypatch.setattr(meal_solver_service, "get_profile", fake_get_profile)
    monkeypatch.setattr(meal_solver_service, "get_recipe_candidates", fake_get_recipe_candidates)
    monkeypatch.setattr(meal_solver_service, "solve_daily_plan", lambda solver_input: sentinel)

    result = meal_solver_service.solve_daily_plan_preview(
        db=object(),
        user=SimpleNamespace(id=uuid4()),
        payload=DailySolverPreviewRequest(max_total_time_minutes=20),
    )

    assert result is sentinel
    assert calls["candidate_kwargs"]["meal_type"] is None
    assert calls["candidate_kwargs"]["max_total_time_minutes"] == 20
    assert calls["candidate_kwargs"]["require_complete_nutrition"] is True


def test_daily_solver_preview_requires_authentication() -> None:
    response = run_async(
        api_request("POST", "/api/v1/meal-plans/solve/preview", json={})
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_daily_solver_preview_valid_request_succeeds(solver_db) -> None:
    db, track_email, _ = solver_db
    seed_development_foods(db)
    seed_development_recipes(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)

    response = solve_preview(token, {})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"optimal", "feasible"}
    meal_types = {meal["meal_type"] for meal in body["meals"]}
    assert {"breakfast", "lunch", "dinner"}.issubset(meal_types)
    recipe_ids = [meal["recipe_id"] for meal in body["meals"]]
    assert len(recipe_ids) == len(set(recipe_ids))

    for code in ["calories", "protein", "carbohydrates", "fat"]:
        expected_total = sum(meal["nutrition"][code] for meal in body["meals"])
        assert body["daily_totals"][code] == pytest.approx(expected_total)
    assert {item["nutrient_code"] for item in body["deviations"]} == {
        "calories",
        "protein",
        "carbohydrates",
        "fat",
    }
    assert "calcium" in {
        item["nutrient_code"] for item in body["micronutrient_coverage"]
    }


def test_archived_recipe_never_reaches_final_plan(solver_db) -> None:
    db, track_email, track_recipe = solver_db
    seed_development_foods(db)
    seed_development_recipes(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)

    recipe = (
        db.query(Recipe)
        .filter(Recipe.source == DEV_RECIPE_SEED_SOURCE, Recipe.name == "Greek Yogurt Oat Bowl")
        .one()
    )
    archived_copy = Recipe(
        name=f"Archived Solver Breakfast {uuid4().hex}",
        description=recipe.description,
        servings=recipe.servings,
        prep_time_minutes=recipe.prep_time_minutes,
        cook_time_minutes=recipe.cook_time_minutes,
        total_time_minutes=recipe.total_time_minutes,
        difficulty=recipe.difficulty,
        instructions_summary=recipe.instructions_summary,
        active=False,
        source="test",
    )
    db.add(archived_copy)
    db.flush()
    track_recipe(archived_copy.id)
    db.commit()

    response = solve_preview(
        token,
        {"meal_slots": [{"meal_type": "breakfast", "required": True}]},
    )

    assert response.status_code == 200
    selected_ids = {meal["recipe_id"] for meal in response.json()["meals"]}
    assert str(archived_copy.id) not in selected_ids


def test_daily_solver_preview_reports_missing_slot_candidate(solver_db) -> None:
    db, track_email, _ = solver_db
    seed_development_foods(db)
    seed_development_recipes(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token, equipment=[])

    response = solve_preview(
        token,
        {
            "meal_slots": [{"meal_type": "dinner", "required": True}],
            "required_tags": ["vegetarian"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "infeasible"
    assert "missing_meal_slot_candidate:dinner" in body["infeasibility_reasons"]


def test_daily_solver_preview_restrictive_request_reports_no_candidates(solver_db) -> None:
    db, track_email, _ = solver_db
    seed_development_foods(db)
    seed_development_recipes(db)
    token = register_and_login(track_email(unique_email()))
    create_profile(token)

    recipe_ids = [str(recipe.id) for recipe in db.query(Recipe).filter(Recipe.active.is_(True)).all()]
    response = solve_preview(
        token,
        {
            "meal_slots": [{"meal_type": "breakfast", "required": True}],
            "excluded_recipe_ids": recipe_ids,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "infeasible"
    assert body["infeasibility_reasons"] == ["no_eligible_candidates"]
