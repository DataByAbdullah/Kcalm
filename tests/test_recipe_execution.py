from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal, engine
from app.core.exceptions import APIErrorException
from app.models.recipe import Recipe
from app.models.recipe_execution import RecipeExecutionSession
from app.models.user import User
from app.schemas.recipe_execution import RecipeExecutionStartRequest
from app.services import recipe_execution_service
from app.services.recipe_execution_service import start_recipe_execution_session
from tests.test_meal_plan_persistence import (
    api_request,
    auth_headers,
    create_plan,
    create_profile,
    create_recipe,
    plan_body,
    recipe_payload,
    register_and_login,
    run_async,
    setup_seed_data,
    unique_email,
)


@pytest.fixture(autouse=True)
def require_recipe_execution_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {
                "users",
                "foods",
                "recipes",
                "recipe_steps",
                "meal_plans",
                "meal_plan_items",
                "recipe_execution_sessions",
                "recipe_execution_step_snapshots",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("recipe execution tables are not migrated")
            recipe_step_columns = {
                column["name"] for column in inspector.get_columns("recipe_steps")
            }
            if not {"phase", "timer_seconds"}.issubset(recipe_step_columns):
                pytest.skip("recipe step execution metadata columns are not migrated")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def execution_db():
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

    db.rollback()
    for email in created_emails:
        user = db.query(User).filter(User.email == email).one_or_none()
        if user is not None:
            db.delete(user)
    db.commit()

    for recipe_id in created_recipe_ids:
        recipe = db.get(Recipe, recipe_id)
        if recipe is not None:
            db.delete(recipe)
    db.commit()
    db.close()


def execution_recipe_payload(db, name: str | None = None) -> dict:
    payload = recipe_payload(
        db,
        name=name or f"Execution Recipe {uuid4().hex}",
        tags=["dinner", "high_protein"],
        food_source_ids=["dev_chicken_breast", "dev_cooked_rice"],
        equipment=["oven", "stovetop"],
    )
    payload["prep_time_minutes"] = 5
    payload["cook_time_minutes"] = 15
    payload["steps"] = [
        {
            "position": 1,
            "instruction": "Set out the ingredients.",
            "phase": "prep",
            "duration_seconds": 120,
            "timer_required": False,
            "cue_action": "prep",
            "animation_key": "prep_counter",
            "visual_cue": "ingredients_ready",
        },
        {
            "position": 2,
            "instruction": "Bake for 8 minutes.",
            "phase": "cook",
            "duration_seconds": 600,
            "timer_required": True,
            "timer_seconds": 480,
            "cue_action": "bake",
            "media_asset_key": "bake_loop",
        },
        {
            "position": 3,
            "instruction": "Plate and serve.",
            "phase": "serve",
            "duration_seconds": 60,
            "timer_required": False,
        },
    ]
    return payload


def create_execution_recipe(db, token: str, track_recipe) -> dict:
    return create_recipe(
        db,
        token,
        track_recipe,
        execution_recipe_payload(db),
    )


def start_direct(token: str, recipe_id: str, servings: float = 1.0):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/recipes/{recipe_id}/execution-sessions",
            headers=auth_headers(token),
            json={"servings": servings},
        )
    )


def start_from_plan_item(token: str, meal_plan_id: str, meal_plan_item_id: str):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/execution-session",
            headers=auth_headers(token),
        )
    )


def get_session(token: str, session_id: str):
    return run_async(
        api_request(
            "GET",
            f"/api/v1/recipe-execution-sessions/{session_id}",
            headers=auth_headers(token),
        )
    )


def progress_session(token: str, session_id: str, current_step_index: int):
    return run_async(
        api_request(
            "PATCH",
            f"/api/v1/recipe-execution-sessions/{session_id}/progress",
            headers=auth_headers(token),
            json={"current_step_index": current_step_index},
        )
    )


def complete_step(token: str, session_id: str, step_index: int):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/recipe-execution-sessions/{session_id}/steps/{step_index}/complete",
            headers=auth_headers(token),
        )
    )


def complete_session(token: str, session_id: str):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/recipe-execution-sessions/{session_id}/complete",
            headers=auth_headers(token),
        )
    )


def abandon_session(token: str, session_id: str):
    return run_async(
        api_request(
            "POST",
            f"/api/v1/recipe-execution-sessions/{session_id}/abandon",
            headers=auth_headers(token),
        )
    )


def create_user_plan(db, track_email, plan_date: str = "2027-04-01") -> tuple[str, dict]:
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email("execution-plan")))
    create_profile(token)
    response = create_plan(token, plan_body(plan_date=plan_date))
    assert response.status_code == 201, response.text
    return token, response.json()


def test_recipe_execution_endpoints_require_authentication() -> None:
    recipe_id = uuid4()
    session_id = uuid4()
    meal_plan_id = uuid4()
    meal_plan_item_id = uuid4()

    responses = [
        run_async(
            api_request(
                "POST",
                f"/api/v1/recipes/{recipe_id}/execution-sessions",
                json={"servings": 1.0},
            )
        ),
        run_async(api_request("GET", f"/api/v1/recipe-execution-sessions/{session_id}")),
        run_async(
            api_request(
                "PATCH",
                f"/api/v1/recipe-execution-sessions/{session_id}/progress",
                json={"current_step_index": 1},
            )
        ),
        run_async(
            api_request(
                "POST",
                f"/api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/execution-session",
            )
        ),
    ]

    assert {response.status_code for response in responses} == {401}
    assert all(response.json()["error"]["code"] == "INVALID_TOKEN" for response in responses)


def test_start_direct_recipe_session_snapshots_steps_timers_and_equipment(execution_db) -> None:
    db, track_email, track_recipe = execution_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email("execution")))
    recipe = create_execution_recipe(db, token, track_recipe)

    response = start_direct(token, recipe["id"], servings=1.5)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["recipe_id"] == recipe["id"]
    assert body["meal_plan_id"] is None
    assert body["status"] == "in_progress"
    assert body["current_step_index"] == 0
    assert body["servings"] == pytest.approx(1.5)
    assert body["total_estimated_time_minutes"] == 20
    assert body["required_equipment"] == ["oven", "stovetop"]
    assert body["step_count"] == 3
    assert [step["step_index"] for step in body["steps"]] == [0, 1, 2]
    assert [step["phase"] for step in body["steps"]] == ["prep", "cook", "serve"]
    assert body["steps"][1]["timer_required"] is True
    assert body["steps"][1]["timer_seconds"] == 480
    assert body["steps"][1]["duration_seconds"] == 600
    assert body["steps"][0]["animation_key"] == "prep_counter"
    assert body["steps"][1]["media_asset_key"] == "bake_loop"
    assert body["ingredients"]


def test_invalid_and_inactive_recipes_are_rejected(execution_db) -> None:
    db, track_email, track_recipe = execution_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email("execution")))
    recipe = create_execution_recipe(db, token, track_recipe)

    invalid_response = start_direct(token, str(uuid4()))
    archive_response = run_async(
        api_request(
            "DELETE",
            f"/api/v1/recipes/{recipe['id']}",
            headers=auth_headers(token),
        )
    )
    inactive_response = start_direct(token, recipe["id"])

    assert invalid_response.status_code == 404
    assert invalid_response.json()["error"]["code"] == "RECIPE_NOT_FOUND"
    assert archive_response.status_code == 204
    assert inactive_response.status_code == 404
    assert inactive_response.json()["error"]["code"] == "RECIPE_NOT_FOUND"


def test_recipe_execution_servings_validation(execution_db) -> None:
    db, track_email, track_recipe = execution_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email("execution")))
    recipe = create_execution_recipe(db, token, track_recipe)

    response = start_direct(token, recipe["id"], servings=0)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_start_from_owned_meal_plan_item_uses_item_context(execution_db) -> None:
    db, track_email, _ = execution_db
    token, plan = create_user_plan(db, track_email, plan_date="2027-04-02")
    item = plan["meals"][0]

    response = start_from_plan_item(token, plan["meal_plan_id"], item["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["meal_plan_id"] == plan["meal_plan_id"]
    assert body["meal_plan_item_id"] == item["id"]
    assert body["recipe_id"] == item["recipe_id"]
    assert body["recipe_name"] == item["recipe_name"]
    assert body["servings"] == pytest.approx(item["servings"])
    assert body["ingredients"]
    assert body["step_count"] >= 1


def test_other_user_cannot_start_or_read_execution_session(execution_db) -> None:
    db, track_email, _ = execution_db
    owner_token, plan = create_user_plan(db, track_email, plan_date="2027-04-03")
    other_token = register_and_login(track_email(unique_email("execution-other")))
    create_profile(other_token)
    item = plan["meals"][0]

    denied_start = start_from_plan_item(other_token, plan["meal_plan_id"], item["id"])
    created = start_from_plan_item(owner_token, plan["meal_plan_id"], item["id"]).json()
    denied_get = get_session(other_token, created["session_id"])

    assert denied_start.status_code == 404
    assert denied_start.json()["error"]["code"] == "MEAL_PLAN_NOT_FOUND"
    assert denied_get.status_code == 404
    assert denied_get.json()["error"]["code"] == "RECIPE_EXECUTION_SESSION_NOT_FOUND"


def test_recipe_edits_after_start_do_not_change_execution_snapshot(execution_db) -> None:
    db, track_email, track_recipe = execution_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email("execution")))
    recipe = create_execution_recipe(db, token, track_recipe)
    started = start_direct(token, recipe["id"]).json()
    original_instruction = started["steps"][1]["instruction"]
    original_timer_seconds = started["steps"][1]["timer_seconds"]

    patch_response = run_async(
        api_request(
            "PATCH",
            f"/api/v1/recipes/{recipe['id']}",
            headers=auth_headers(token),
            json={
                "name": "Edited Execution Recipe",
                "steps": [
                    {
                        "position": 1,
                        "instruction": "Changed step.",
                        "phase": "cook",
                        "duration_seconds": 30,
                        "timer_required": True,
                        "timer_seconds": 30,
                    }
                ],
            },
        )
    )
    reloaded = get_session(token, started["session_id"]).json()

    assert patch_response.status_code == 200, patch_response.text
    assert reloaded["recipe_name"] == recipe["name"]
    assert reloaded["steps"][1]["instruction"] == original_instruction
    assert reloaded["steps"][1]["timer_seconds"] == original_timer_seconds
    assert reloaded["step_count"] == 3


def test_progress_complete_step_and_complete_session(execution_db) -> None:
    db, track_email, track_recipe = execution_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email("execution")))
    recipe = create_execution_recipe(db, token, track_recipe)
    session_id = start_direct(token, recipe["id"]).json()["session_id"]

    progressed = progress_session(token, session_id, 2)
    invalid = progress_session(token, session_id, 99)
    step_completed = complete_step(token, session_id, 0)
    completed = complete_session(token, session_id)
    progress_after_complete = progress_session(token, session_id, 1)

    assert progressed.status_code == 200
    assert progressed.json()["current_step_index"] == 2
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_EXECUTION_STEP_INDEX"
    assert step_completed.status_code == 200
    assert step_completed.json()["steps"][0]["completed"] is True
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None
    assert all(step["completed"] for step in completed.json()["steps"])
    assert progress_after_complete.status_code == 409
    assert progress_after_complete.json()["error"]["code"] == "EXECUTION_SESSION_COMPLETED"


def test_abandoned_session_cannot_continue_and_in_progress_session_resumes(execution_db) -> None:
    db, track_email, track_recipe = execution_db
    setup_seed_data(db)
    token = register_and_login(track_email(unique_email("execution")))
    recipe = create_execution_recipe(db, token, track_recipe)
    resume_session_id = start_direct(token, recipe["id"]).json()["session_id"]
    abandon_session_id = start_direct(token, recipe["id"]).json()["session_id"]

    progress_session(token, resume_session_id, 1)
    resumed = get_session(token, resume_session_id)
    abandoned = abandon_session(token, abandon_session_id)
    progress_after_abandon = progress_session(token, abandon_session_id, 1)

    assert resumed.status_code == 200
    assert resumed.json()["status"] == "in_progress"
    assert resumed.json()["current_step_index"] == 1
    assert abandoned.status_code == 200
    assert abandoned.json()["status"] == "abandoned"
    assert progress_after_abandon.status_code == 409
    assert progress_after_abandon.json()["error"]["code"] == "EXECUTION_SESSION_ABANDONED"


def test_duplicate_active_meal_plan_item_session_prevented_but_history_preserved(
    execution_db,
) -> None:
    db, track_email, _ = execution_db
    token, plan = create_user_plan(db, track_email, plan_date="2027-04-04")
    item = plan["meals"][0]

    first = start_from_plan_item(token, plan["meal_plan_id"], item["id"])
    duplicate = start_from_plan_item(token, plan["meal_plan_id"], item["id"])
    complete_session(token, first.json()["session_id"])
    historical_allowed = start_from_plan_item(token, plan["meal_plan_id"], item["id"])

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EXECUTION_SESSION_ALREADY_ACTIVE"
    assert historical_allowed.status_code == 201
    assert historical_allowed.json()["session_id"] != first.json()["session_id"]


def test_execution_session_start_rolls_back_when_snapshot_save_fails(
    execution_db,
    monkeypatch,
) -> None:
    db, track_email, track_recipe = execution_db
    setup_seed_data(db)
    email = track_email(unique_email("execution-rollback"))
    token = register_and_login(email)
    recipe = create_execution_recipe(db, token, track_recipe)
    user = db.query(User).filter(User.email == email).one()
    before_count = db.query(RecipeExecutionSession).count()
    original_create_snapshot = recipe_execution_service.create_execution_snapshot

    def failing_create_snapshot(*args, **kwargs):
        original_create_snapshot(*args, **kwargs)
        raise SQLAlchemyError("forced recipe execution snapshot failure")

    monkeypatch.setattr(
        recipe_execution_service,
        "create_execution_snapshot",
        failing_create_snapshot,
    )

    with pytest.raises(APIErrorException) as exc_info:
        start_recipe_execution_session(
            db=db,
            user=user,
            recipe_id=UUID(recipe["id"]),
            payload=RecipeExecutionStartRequest(servings=1.0),
        )

    assert exc_info.value.code == "RECIPE_EXECUTION_SAVE_FAILED"
    assert db.query(RecipeExecutionSession).count() == before_count
