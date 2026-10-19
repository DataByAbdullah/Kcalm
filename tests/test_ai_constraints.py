from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from app.core.enums import FoodSource
from app.core.config import Settings
from app.core.database import SessionLocal, engine
from app.core.exceptions import APIErrorException
from app.integrations.openai_client import (
    SYSTEM_PROMPT,
    OpenAIConstraintClientError,
    OpenAINaturalLanguageConstraintClient,
)
from app.models.food import Food
from app.models.meal_plan import MealPlan
from app.models.recipe import Recipe
from app.models.user import User
from app.schemas.ai import NaturalLanguageMealConstraintLLMOutput
from app.services import ai_constraint_service
from app.services.ai_constraint_service import (
    interpret_natural_language_constraints,
    preview_ai_meal_options,
)
from app.services.recipe_candidate_service import CandidateFilterResult
from tests.test_meal_plan_persistence import (
    api_request,
    auth_headers,
    create_plan,
    create_profile,
    create_recipe,
    food_id,
    plan_body,
    recipe_payload,
    register_and_login,
    run_async,
    setup_seed_data,
    unique_email,
)


@pytest.fixture(autouse=True)
def require_ai_tables():
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            required_tables = {
                "users",
                "user_profiles",
                "foods",
                "recipes",
                "recipe_ingredients",
                "meal_plans",
                "meal_plan_items",
                "meal_plan_item_nutrients",
            }
            if not required_tables.issubset(set(inspector.get_table_names())):
                pytest.skip("AI constraint tests require migrated core tables")
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL is not available: {exc}")


@pytest.fixture
def ai_db():
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


class FakeInterpreter:
    def __init__(self, output=None, error: OpenAIConstraintClientError | None = None):
        self.output = output or NaturalLanguageMealConstraintLLMOutput()
        self.error = error

    def interpret_constraints(self, text: str):
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            output=self.output,
            model="mock-model",
            latency_seconds=0.01,
        )


def openai_client_settings() -> Settings:
    return Settings(openai_api_key="test-openai-key", openai_model="test-model")


def fake_openai_response(
    *,
    parsed=None,
    status: str = "completed",
    incomplete_reason: str | None = None,
    output_text: str = "",
    output=None,
):
    incomplete_details = (
        SimpleNamespace(reason=incomplete_reason) if incomplete_reason is not None else None
    )
    return SimpleNamespace(
        output_parsed=parsed,
        status=status,
        incomplete_details=incomplete_details,
        output=output or [],
        output_text=output_text,
    )


def patch_openai_parse(monkeypatch, response):
    import openai

    calls: list[dict] = []

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs)
            return response

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    return calls


def patch_interpreter(monkeypatch, output):
    fake = FakeInterpreter(output=output)
    monkeypatch.setattr(ai_constraint_service, "get_ai_interpreter", lambda: fake)
    return fake


def user_for_token(db, email: str) -> User:
    return db.query(User).filter(User.email == email).one()


def create_ai_user(db, track_email) -> tuple[str, str, User]:
    setup_seed_data(db)
    email = track_email(unique_email("ai"))
    token = register_and_login(email)
    create_profile(token)
    return email, token, user_for_token(db, email)


def ai_post(path: str, token: str, body: dict):
    return run_async(
        api_request(
            "POST",
            path,
            headers=auth_headers(token),
            json=body,
        )
    )


def create_ai_test_food(db, name: str) -> Food:
    food = Food(
        name=name,
        source=FoodSource.INTERNAL,
        source_food_id=f"ai_{name.lower().replace(' ', '_')}_{uuid4().hex}",
        category="test",
        description=f"Test-only {name} food for AI avoidance resolution.",
    )
    db.add(food)
    db.commit()
    db.refresh(food)
    return food


def lunch_item(plan: dict) -> dict:
    return next(meal for meal in plan["meals"] if meal["meal_type"] == "lunch")


def recipe_ids(plan: dict) -> list[str]:
    return [meal["recipe_id"] for meal in plan["meals"]]


def test_ai_endpoints_require_authentication() -> None:
    response = run_async(
        api_request("POST", "/api/v1/ai/constraints/interpret", json={"text": "quick dinner"})
    )
    options = run_async(
        api_request("POST", "/api/v1/ai/meal-options", json={"text": "quick dinner"})
    )
    swap = run_async(
        api_request(
            "POST",
            f"/api/v1/meal-plans/{uuid4()}/items/{uuid4()}/ai-swap",
            json={"text": "quick dinner"},
        )
    )

    assert response.status_code == 401
    assert options.status_code == 401
    assert swap.status_code == 401


def test_openai_client_returns_parsed_structured_response(monkeypatch) -> None:
    parsed = NaturalLanguageMealConstraintLLMOutput(
        requested_action="find_options",
        meal_type="dinner",
        required_tags=["quick"],
    )
    calls = patch_openai_parse(
        monkeypatch,
        fake_openai_response(parsed=parsed),
    )

    result = OpenAINaturalLanguageConstraintClient(
        settings=openai_client_settings()
    ).interpret_constraints("quick dinner")

    assert result.output == parsed
    assert result.model == "test-model"
    assert calls[0]["text_format"] is NaturalLanguageMealConstraintLLMOutput
    assert "text" not in calls[0]


def test_openai_client_returns_clarification_request_for_lighter(monkeypatch) -> None:
    question = "Do you mean lower calories, lower fat, or a smaller portion?"
    parsed = NaturalLanguageMealConstraintLLMOutput(
        requested_action="find_options",
        clarification_required=True,
        clarification_question=question,
    )
    patch_openai_parse(monkeypatch, fake_openai_response(parsed=parsed))

    result = OpenAINaturalLanguageConstraintClient(
        settings=openai_client_settings()
    ).interpret_constraints("Give me something lighter")

    assert "For ambiguous language like \"lighter\"" in SYSTEM_PROMPT
    assert question in SYSTEM_PROMPT
    assert result.output.clarification_required is True
    assert result.output.clarification_question == question
    assert result.output.max_total_time_minutes is None
    assert result.output.required_tags == []


def test_openai_client_refusal_is_controlled(monkeypatch) -> None:
    response = fake_openai_response(
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(
                        type="refusal",
                        refusal="I cannot help with that request.",
                    )
                ],
            )
        ],
    )
    patch_openai_parse(monkeypatch, response)

    with pytest.raises(OpenAIConstraintClientError) as exc:
        OpenAINaturalLanguageConstraintClient(
            settings=openai_client_settings()
        ).interpret_constraints("unsafe request")

    assert exc.value.category == "refusal"


def test_openai_client_incomplete_max_tokens_is_controlled(monkeypatch) -> None:
    response = fake_openai_response(
        status="incomplete",
        incomplete_reason="max_output_tokens",
        output_text='{"requested_action":"find_options"',
    )
    patch_openai_parse(monkeypatch, response)

    with pytest.raises(OpenAIConstraintClientError) as exc:
        OpenAINaturalLanguageConstraintClient(
            settings=openai_client_settings()
        ).interpret_constraints("quick dinner")

    assert exc.value.category == "incomplete_response"


def test_openai_client_text_without_parsed_output_is_malformed(monkeypatch) -> None:
    response = fake_openai_response(
        output_text='{"requested_action":"find_options","unexpected":true}',
    )
    patch_openai_parse(monkeypatch, response)

    with pytest.raises(OpenAIConstraintClientError) as exc:
        OpenAINaturalLanguageConstraintClient(
            settings=openai_client_settings()
        ).interpret_constraints("quick dinner")

    assert exc.value.category == "malformed_response"


def test_openai_client_genuinely_empty_output_is_controlled(monkeypatch) -> None:
    patch_openai_parse(monkeypatch, fake_openai_response())

    with pytest.raises(OpenAIConstraintClientError) as exc:
        OpenAINaturalLanguageConstraintClient(
            settings=openai_client_settings()
        ).interpret_constraints("quick dinner")

    assert exc.value.category == "empty_output"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ({"meal_type": "dinner"}, {"meal_type": "dinner"}),
        ({"required_tags": ["fast"]}, {"required_tags": ["quick"]}),
        ({"max_total_time_minutes": 15}, {"max_total_time_minutes": 15}),
        ({"required_tags": ["veggie"]}, {"required_tags": ["vegetarian"]}),
        ({"required_tags": ["no dairy"]}, {"required_tags": ["dairy_free"]}),
        ({"required_tags": ["protein heavy"]}, {"required_tags": ["high_protein"]}),
    ],
)
def test_interpretation_normalizes_supported_intents(ai_db, output, expected) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)

    interpreted = interpret_natural_language_constraints(
        db=db,
        user=user,
        text="mock text",
        interpreter=FakeInterpreter(output=NaturalLanguageMealConstraintLLMOutput(**output)),
    ).constraints

    for key, value in expected.items():
        assert getattr(interpreted, key) == value


def test_combined_constraints_resolve_food_avoidance_and_soft_preference(ai_db) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)
    output = NaturalLanguageMealConstraintLLMOutput(
        requested_action="find_options",
        meal_type="dinner",
        max_total_time_minutes=15,
        required_tags=["fast", "protein heavy", "veggie", "no dairy"],
        avoid_food_names=["chicken"],
        preference_food_names=["yogurt"],
    )

    interpreted = interpret_natural_language_constraints(
        db=db,
        user=user,
        text="I want a quick high protein dinner with no chicken and yogurt sounds good",
        interpreter=FakeInterpreter(output=output),
    ).constraints

    assert interpreted.meal_type == "dinner"
    assert interpreted.max_total_time_minutes == 15
    assert interpreted.required_tags == ["quick", "high_protein", "vegetarian", "dairy_free"]
    assert interpreted.avoid_food_names == ["chicken"]
    assert interpreted.preference_food_names == ["yogurt"]
    assert interpreted.resolved_avoid_foods[0].food_name == "Chicken Breast"
    assert interpreted.excluded_recipe_ids


def test_ambiguous_unsupported_and_allergy_requests_remain_structured(ai_db) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)
    output = NaturalLanguageMealConstraintLLMOutput(
        unsupported_constraints=["restaurant", "peanut_allergy"],
        clarification_required=True,
        clarification_question="Do you mean fewer calories or a smaller portion?",
    )

    interpreted = interpret_natural_language_constraints(
        db=db,
        user=user,
        text="Find me a peanut-safe restaurant meal but make it lighter",
        interpreter=FakeInterpreter(output=output),
    ).constraints

    assert interpreted.clarification_required is True
    assert interpreted.clarification_question
    assert interpreted.unsupported_constraints == [
        "restaurant",
        ai_constraint_service.ALLERGY_SAFETY_UNSUPPORTED,
    ]
    assert interpreted.required_tags == []


@pytest.mark.parametrize(
    ("text", "avoid_food_names"),
    [
        ("I have a peanut allergy", ["peanuts"]),
        ("I'm allergic to shellfish", ["shellfish"]),
        ("No sesame, I'm allergic", ["sesame"]),
        ("I need something safe for my nut allergy", ["tree nuts"]),
        ("I cannot eat eggs because of an allergy", ["eggs"]),
    ],
)
def test_allergy_safety_intent_is_unsupported_not_food_avoidance(
    ai_db,
    text,
    avoid_food_names,
) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)
    output = NaturalLanguageMealConstraintLLMOutput(
        meal_type="dinner",
        avoid_food_names=avoid_food_names,
    )

    interpreted = interpret_natural_language_constraints(
        db=db,
        user=user,
        text=text,
        interpreter=FakeInterpreter(output=output),
    ).constraints

    assert interpreted.meal_type == "dinner"
    assert interpreted.avoid_food_names == []
    assert interpreted.resolved_avoid_foods == []
    assert interpreted.excluded_recipe_ids == []
    assert interpreted.unsupported_constraints == [
        ai_constraint_service.ALLERGY_SAFETY_UNSUPPORTED
    ]
    assert interpreted.clarification_required is False


def test_dairy_allergy_is_unsupported_not_food_avoidance(ai_db) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)
    output = NaturalLanguageMealConstraintLLMOutput(
        meal_type="lunch",
        avoid_food_names=["dairy", "milk"],
    )

    interpreted = interpret_natural_language_constraints(
        db=db,
        user=user,
        text="I have a dairy allergy, give me lunch",
        interpreter=FakeInterpreter(output=output),
    ).constraints

    assert interpreted.meal_type == "lunch"
    assert interpreted.avoid_food_names == []
    assert interpreted.resolved_avoid_foods == []
    assert interpreted.unsupported_constraints == [
        ai_constraint_service.ALLERGY_SAFETY_UNSUPPORTED
    ]


@pytest.mark.parametrize(
    ("text", "food_name", "avoid_food_name"),
    [
        ("I don't want peanuts", "Peanuts", "peanuts"),
        ("No shellfish tonight", "Shellfish", "shellfish"),
        ("Avoid eggs", "Eggs", "eggs"),
        ("I'd rather not have sesame", "Sesame", "sesame"),
    ],
)
def test_non_allergy_avoidance_uses_normal_food_resolution(
    ai_db,
    text,
    food_name,
    avoid_food_name,
) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)
    food = create_ai_test_food(db, food_name)

    try:
        interpreted = interpret_natural_language_constraints(
            db=db,
            user=user,
            text=text,
            interpreter=FakeInterpreter(
                output=NaturalLanguageMealConstraintLLMOutput(
                    avoid_food_names=[avoid_food_name],
                )
            ),
        ).constraints
    finally:
        db.delete(food)
        db.commit()

    assert interpreted.avoid_food_names == [avoid_food_name]
    assert interpreted.resolved_avoid_foods[0].food_name == food_name
    assert interpreted.unsupported_constraints == []


def test_allergy_request_preserves_supported_non_allergy_constraints(ai_db) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)

    interpreted = interpret_natural_language_constraints(
        db=db,
        user=user,
        text="I'm allergic to peanuts and want a quick dinner",
        interpreter=FakeInterpreter(
            output=NaturalLanguageMealConstraintLLMOutput(
                meal_type="dinner",
                required_tags=["quick"],
                avoid_food_names=["peanuts"],
            )
        ),
    ).constraints

    assert interpreted.meal_type == "dinner"
    assert interpreted.required_tags == ["quick"]
    assert interpreted.avoid_food_names == []
    assert interpreted.unsupported_constraints == [
        ai_constraint_service.ALLERGY_SAFETY_UNSUPPORTED
    ]


def test_mixed_normal_avoidance_and_allergy_preserves_normal_avoidance(ai_db) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)

    interpreted = interpret_natural_language_constraints(
        db=db,
        user=user,
        text="Avoid chicken and also I have a shellfish allergy",
        interpreter=FakeInterpreter(
            output=NaturalLanguageMealConstraintLLMOutput(
                avoid_food_names=["chicken", "shellfish"],
            )
        ),
    ).constraints

    assert interpreted.avoid_food_names == ["chicken"]
    assert interpreted.resolved_avoid_foods[0].food_name == "Chicken Breast"
    assert interpreted.unsupported_constraints == [
        ai_constraint_service.ALLERGY_SAFETY_UNSUPPORTED
    ]


def test_allergy_request_does_not_return_allergy_safe_candidate_claim(ai_db, monkeypatch) -> None:
    db, track_email, _ = ai_db
    _, token, _ = create_ai_user(db, track_email)
    patch_interpreter(
        monkeypatch,
        NaturalLanguageMealConstraintLLMOutput(
            meal_type="dinner",
            avoid_food_names=["peanuts"],
        ),
    )

    response = ai_post(
        "/api/v1/ai/meal-options",
        token,
        {"text": "I have a peanut allergy, give me a safe dinner"},
    )
    body = response.json()

    assert response.status_code == 200, response.text
    assert body["interpretation"]["meal_type"] == "dinner"
    assert body["interpretation"]["avoid_food_names"] == []
    assert body["interpretation"]["unsupported_constraints"] == [
        ai_constraint_service.ALLERGY_SAFETY_UNSUPPORTED
    ]
    assert body["candidate_preview"] is None


def test_non_allergy_unresolved_avoidance_still_fails_backend_validation(ai_db) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)

    with pytest.raises(APIErrorException) as exc:
        interpret_natural_language_constraints(
            db=db,
            user=user,
            text="no moonfruit please",
            interpreter=FakeInterpreter(
                output=NaturalLanguageMealConstraintLLMOutput(
                    avoid_food_names=["moonfruit"],
                )
            ),
        )

    assert exc.value.code == "AI_CONSTRAINT_VALIDATION_FAILED"
    assert exc.value.details["reason"] == "avoid_food_not_resolved"


def test_malformed_ai_response_is_controlled(ai_db) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)

    with pytest.raises(APIErrorException) as exc:
        interpret_natural_language_constraints(
            db=db,
            user=user,
            text="bad model output",
            interpreter=FakeInterpreter(output={"excluded_recipe_ids": [str(uuid4())]}),
        )

    assert exc.value.code == "AI_CONSTRAINT_VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("category", "expected_code"),
    [
        ("timeout", "AI_TIMEOUT"),
        ("rate_limit", "AI_RATE_LIMITED"),
        ("authentication", "AI_AUTHENTICATION_FAILED"),
        ("incomplete_response", "AI_INCOMPLETE_RESPONSE"),
        ("refusal", "AI_REFUSAL"),
    ],
)
def test_openai_client_errors_are_controlled(ai_db, category, expected_code) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)

    with pytest.raises(APIErrorException) as exc:
        interpret_natural_language_constraints(
            db=db,
            user=user,
            text="quick dinner",
            interpreter=FakeInterpreter(
                error=OpenAIConstraintClientError(category, f"{category} failure")
            ),
        )

    assert exc.value.code == expected_code


def test_unknown_ai_generated_tag_is_rejected(ai_db) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)

    with pytest.raises(APIErrorException) as exc:
        interpret_natural_language_constraints(
            db=db,
            user=user,
            text="make it paleo",
            interpreter=FakeInterpreter(
                output=NaturalLanguageMealConstraintLLMOutput(required_tags=["paleo"])
            ),
        )

    assert exc.value.code == "AI_CONSTRAINT_VALIDATION_FAILED"
    assert exc.value.details["reason"] == "unsupported_ai_generated_tag"


def test_candidate_preview_uses_existing_candidate_service(ai_db, monkeypatch) -> None:
    db, track_email, _ = ai_db
    _, _, user = create_ai_user(db, track_email)
    output = NaturalLanguageMealConstraintLLMOutput(
        meal_type="lunch",
        required_tags=["quick"],
        avoid_food_names=["chicken"],
    )
    calls: list[dict] = []

    def fake_candidates(**kwargs):
        calls.append(kwargs)
        return CandidateFilterResult(
            candidates=[],
            total_eligible=0,
            exclusion_summary={},
            excluded=[],
            allergy_filtering_supported=False,
            unsupported_dietary_restrictions=[],
            filter_order=[],
        )

    monkeypatch.setattr(ai_constraint_service, "get_recipe_candidates", fake_candidates)

    interpreted, candidate_result = preview_ai_meal_options(
        db=db,
        user=user,
        text="quick lunch without chicken",
        interpreter=FakeInterpreter(output=output),
    )

    assert candidate_result is not None
    assert calls
    assert calls[0]["meal_type"] == "lunch"
    assert calls[0]["required_tags"] == ["quick"]
    assert calls[0]["excluded_recipe_ids"] == interpreted.constraints.excluded_recipe_ids


def test_ai_meal_options_endpoint_returns_filtered_candidates(ai_db, monkeypatch) -> None:
    db, track_email, _ = ai_db
    _, token, _ = create_ai_user(db, track_email)
    patch_interpreter(
        monkeypatch,
        NaturalLanguageMealConstraintLLMOutput(
            meal_type="lunch",
            required_tags=["quick"],
            avoid_food_names=["chicken"],
        ),
    )

    response = ai_post(
        "/api/v1/ai/meal-options",
        token,
        {"text": "Give me a quick lunch with no chicken"},
    )
    body = response.json()

    assert response.status_code == 200, response.text
    assert body["interpretation"]["meal_type"] == "lunch"
    assert body["interpretation"]["required_tags"] == ["quick"]
    assert body["interpretation"]["excluded_recipe_ids"]
    assert body["candidate_preview"] is not None
    assert body["candidate_preview"]["total_eligible"] == 0


def test_ai_swap_uses_existing_swap_service_and_preserves_meal_type(ai_db, monkeypatch) -> None:
    db, track_email, track_recipe = ai_db
    setup_seed_data(db)
    email = track_email(unique_email("ai-swap"))
    token = register_and_login(email)
    create_profile(token)
    created = create_plan(token, plan_body(plan_date="2027-05-01"))
    assert created.status_code == 201, created.text
    plan = created.json()
    replacement = create_recipe(
        db,
        token,
        track_recipe,
        {
            **recipe_payload(
                db,
                name=f"AI Dairy Free Lunch {uuid4().hex}",
                tags=["lunch", "quick", "dairy_free", "high_protein"],
                food_source_ids=["dev_salmon", "dev_cooked_rice"],
                equipment=[],
            ),
            "cook_time_minutes": 5,
        },
    )
    target = lunch_item(plan)
    patch_interpreter(
        monkeypatch,
        NaturalLanguageMealConstraintLLMOutput(
            requested_action="swap_meal",
            required_tags=["quick", "dairy_free"],
        ),
    )

    response = ai_post(
        f"/api/v1/meal-plans/{plan['meal_plan_id']}/items/{target['id']}/ai-swap",
        token,
        {"text": "Give me something quicker and dairy free"},
    )
    body = response.json()
    swapped_lunch = next(meal for meal in body["meals"] if meal["id"] == target["id"])

    assert response.status_code == 200, response.text
    assert swapped_lunch["meal_type"] == "lunch"
    assert swapped_lunch["recipe_id"] == replacement["id"]
    assert swapped_lunch["recipe_id"] != target["recipe_id"]
    assert set(recipe_ids(body)) - {replacement["id"]} == set(recipe_ids(plan)) - {target["recipe_id"]}


def test_failed_ai_interpretation_does_not_mutate_plan(ai_db, monkeypatch) -> None:
    db, track_email, _ = ai_db
    _, token, _ = create_ai_user(db, track_email)
    created = create_plan(token, plan_body(plan_date="2027-05-02"))
    assert created.status_code == 201, created.text
    plan = created.json()
    target = lunch_item(plan)
    monkeypatch.setattr(
        ai_constraint_service,
        "get_ai_interpreter",
        lambda: FakeInterpreter(
            error=OpenAIConstraintClientError("timeout", "timeout failure")
        ),
    )

    response = ai_post(
        f"/api/v1/meal-plans/{plan['meal_plan_id']}/items/{target['id']}/ai-swap",
        token,
        {"text": "something quicker"},
    )
    persisted = db.get(MealPlan, UUID(plan["meal_plan_id"]))

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "AI_TIMEOUT"
    assert [str(item.recipe_id) for item in persisted.items] == recipe_ids(plan)


def test_failed_swap_does_not_mutate_plan(ai_db, monkeypatch) -> None:
    db, track_email, _ = ai_db
    _, token, _ = create_ai_user(db, track_email)
    created = create_plan(token, plan_body(plan_date="2027-05-03"))
    assert created.status_code == 201, created.text
    plan = created.json()
    target = lunch_item(plan)
    patch_interpreter(
        monkeypatch,
        NaturalLanguageMealConstraintLLMOutput(
            requested_action="swap_meal",
            required_tags=["vegan"],
        ),
    )

    response = ai_post(
        f"/api/v1/meal-plans/{plan['meal_plan_id']}/items/{target['id']}/ai-swap",
        token,
        {"text": "make lunch vegan"},
    )
    persisted = db.get(MealPlan, UUID(plan["meal_plan_id"]))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_SWAP_CANDIDATE"
    assert [str(item.recipe_id) for item in persisted.items] == recipe_ids(plan)
