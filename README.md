# Kcalm Backend

## Progress and Account APIs

Priority 2/3 backend support now includes dated weight logs and target-weight progress,
manual steps, daily habits/completions, achievements and insights from real records,
notification inbox/read state, password changes with session revocation, account deletion,
JSON export, pescatarian/halal candidate tags, conservative reviewed-allergen filtering,
grocery completion counts, and an honest integration capability catalog.

Exact routes, request/response examples, limits, Postman instructions, migration details,
and provider requirements are in [Frontend API Guide](docs/FRONTEND_API_GUIDE.md).
Run `alembic upgrade head` before using these endpoints. Current head: `20261021_0018`.
Secrets and `.env` are not changed by these additions.
Verification for these extensions: 361 tests passed on a freshly migrated isolated
PostgreSQL database; six-migration downgrade/re-upgrade and compile checks passed.

Kcalm is a backend-only FastAPI service for deterministic nutrition planning, verified food and recipe data, meal-plan generation, logging, and Postman-ready APIs.

This repository currently includes the backend foundation, PostgreSQL, Alembic, authentication, user profile capture, deterministic BMR/TDEE, calorie/macro targets, profile-based micronutrient targets, an internal structured food database, USDA FoodData Central search/import, a structured recipe database, deterministic recipe nutrition calculation, recipe candidate filtering, a non-persisted OR-Tools daily solver preview, persisted one-day meal plans, single-meal swaps, persisted weekly plans, deterministic weekly grocery preview aggregation, persisted smart grocery lists with editable items, ate-as-planned/corrected meal logging with planned-vs-actual summaries, adaptive next-day compensation, recipe execution sessions with immutable step snapshots, and a guarded AI natural-language constraint layer. It intentionally does not include frontend code, grocery delivery integrations, animation rendering, video/image generation, barcode/photo logging, restaurant matching, wearable sync, or AI-sourced nutrition numbers.

## Backend MVP Status

The backend MVP has been hardened end-to-end for frontend integration. The automated suite includes a full integration journey covering register/login, profile creation/update, deterministic target calculation, foods/USDA, recipes, candidate preview, daily plan generation, meal swap, weekly plan generation, grocery list editing, meal logging, actual-summary, adaptive next-day planning, AI constraint/meal-option/swap flows with mocks, and recipe execution progress/completion.

Final validation completed against local Docker PostgreSQL on `127.0.0.1:5433`:

- Alembic current/head: `20261013_0012`.
- Fresh database migration from base to head: passed.
- Full test suite: `299 passed`.
- Compile check: `python -m compileall app` passed.
- Startup smoke: `uvicorn app.main:app --reload`, `/api/v1/health`, `/docs`, and `/openapi.json` passed.

Deferred areas remain intentionally out of backend MVP scope: mobile frontend, actual visual animations, image/video generation, voice assistant, camera/photo meal recognition, barcode scanning, restaurant matching, grocery delivery integrations, wearable integrations, advanced medical/allergen guarantees, generated Postman collection files, and production deployment/DevOps.

## Requirements

- Python 3.12+
- Docker
- Docker Compose
- Google OR-Tools, installed from `requirements.txt` for CP-SAT meal optimization

## Local Setup

Create and activate a virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

If `python3.12` is not available on your machine, use any installed Python 3.12+ executable.

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a local environment file if needed:

```bash
cp .env.example .env
```

Do not commit `.env`.

## PostgreSQL

Local PostgreSQL runs through Docker Compose.

Start the database:

```bash
docker compose up -d db
```

View service status:

```bash
docker compose ps
```

Stop services:

```bash
docker compose down
```

The local development database URL is:

```text
postgresql+psycopg://postgres:postgres@127.0.0.1:5433/kcalm
```

These credentials are for local Docker Compose only.

Kcalm exposes PostgreSQL on `127.0.0.1:5433` to avoid conflicts with any other local PostgreSQL instance using the default host port `5432`.

## Migrations

Alembic is configured to read the database URL from application settings and environment variables.

Check the current revision:

```bash
alembic current
```

Show migration heads:

```bash
alembic heads
```

Run migrations:

```bash
alembic upgrade head
```

Downgrade one revision when it is safe to do so:

```bash
alembic downgrade -1
```

## Run The API

Start the FastAPI development server:

```bash
uvicorn app.main:app --reload
```

API docs:

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

Health endpoint:

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "kcalm-api"
}
```

## Run Tests

```bash
pytest -q
```

Database-backed tests require local PostgreSQL to be running through Docker Compose.
Run one test process per database; suites temporarily create shared recipe fixtures.
Use a dedicated `DATABASE_URL` when running isolated verification or parallel processes.

## Configuration

Supported environment variables:

- `APP_NAME`
- `APP_ENV`
- `API_V1_PREFIX`
- `DATABASE_URL`
- `JWT_SECRET`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `USDA_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_TIMEOUT_SECONDS`

PostgreSQL configuration is provided through `DATABASE_URL`. SQLAlchemy session infrastructure and Alembic migrations manage the application tables.

USDA FoodData Central search and import require `USDA_API_KEY`. Create a free API key through Data.gov from the USDA FoodData Central API Guide at https://fdc.nal.usda.gov/api-guide/, set it in `.env`, and restart FastAPI after changing the value. Do not commit a real key.

OpenAI natural-language constraint endpoints require `OPENAI_API_KEY`. `OPENAI_MODEL` defaults to `gpt-5-mini`, and `OPENAI_TIMEOUT_SECONDS` defaults to `10`. The structured output token cap is a code-level guardrail in `app/integrations/openai_client.py`, not an environment variable. Never commit production secrets in `.env.example` or `.env`.

## Authentication

Authentication uses JSON requests, Argon2 password hashing, and JWT bearer access tokens.

Register:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"testuser@example.com","password":"StrongPassword123"}'
```

Login:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"testuser@example.com","password":"StrongPassword123"}'
```

Use the returned token on protected endpoints:

```bash
curl http://127.0.0.1:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

Example protected request header:

```text
Authorization: Bearer eyJ...
```

## User Profile

Profile endpoints require a bearer token.

Create a profile:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/users/profile \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "age": 29,
    "sex": "male",
    "height_cm": 178,
    "weight_kg": 82,
    "activity_level": "moderate",
    "goal": "fat_loss",
    "target_rate": 0.5,
    "max_cooking_minutes": 20,
    "meals_per_day": 4,
    "allergies": ["peanuts"],
    "dietary_restrictions": ["halal"],
    "preferred_foods": ["chicken", "rice"],
    "disliked_foods": ["mushrooms"],
    "equipment": ["stove", "microwave", "air_fryer"]
  }'
```

Get the current profile:

```bash
curl http://127.0.0.1:8000/api/v1/users/profile \
  -H "Authorization: Bearer <access_token>"
```

Update profile fields:

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/users/profile \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"weight_kg":80,"max_cooking_minutes":15}'
```

Supported profile enums:

- `sex`: `male`, `female`
- `activity_level`: `sedentary`, `light`, `moderate`, `very_active`, `extra_active`
- `goal`: `fat_loss`, `muscle_gain`, `maintenance`, `recomposition`

PATCH behavior:

- Included scalar fields are updated.
- Omitted scalar fields remain unchanged.
- Included list fields replace the current list.
- Omitted list fields remain unchanged.
- An explicit empty list clears that list.

## Nutrition Calculation

The nutrition calculation endpoint requires a bearer token and accepts direct calculation inputs. It does not read the stored profile yet.

Calculation rules:

- BMR uses Mifflin-St Jeor.
- Male BMR: `10 * weight_kg + 6.25 * height_cm - 5 * age + 5`
- Female BMR: `10 * weight_kg + 6.25 * height_cm - 5 * age - 161`
- TDEE: `BMR * activity_multiplier`
- Target calories are calculated from TDEE and goal.
- Protein uses total body weight because lean mass is not collected yet.
- Fat uses a weight-based floor.
- Carbs fill the calories remaining after protein and fat.
- Internal calculations are unrounded; API response values are rounded to one decimal place.

Activity multipliers:

- `sedentary`: `1.2`
- `light`: `1.375`
- `moderate`: `1.55`
- `very_active`: `1.725`
- `extra_active`: `1.9`

Calorie strategy:

- `maintenance`: `target_calories = TDEE`
- `fat_loss`: `target_calories = TDEE - min(target_rate * 1000, 500)`
- `muscle_gain`: `target_calories = TDEE + min(target_rate * 1000, 300)`
- `recomposition`: `target_calories = TDEE`

If `target_rate` is omitted, fat loss uses `0.5` and muscle gain uses `0.25`. Maintenance and recomposition stay at TDEE; any supplied `target_rate` is accepted by validation but does not change calories for those goals.

Macro constants:

- Protein: `4 kcal/g`
- Carbs: `4 kcal/g`
- Fat: `9 kcal/g`

Protein factors:

- `maintenance`: `1.6 g/kg`
- `fat_loss`: `2.0 g/kg`
- `muscle_gain`: `1.8 g/kg`
- `recomposition`: `2.0 g/kg`

Fat floor:

- `0.8 g/kg`

Calculate nutrition targets:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/nutrition/calculate \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "age": 29,
    "sex": "male",
    "height_cm": 178,
    "weight_kg": 82,
    "activity_level": "moderate",
    "goal": "fat_loss",
    "target_rate": 0.5
  }'
```

Expected response for this sample:

```json
{
  "bmr": 1792.5,
  "tdee": 2778.4,
  "target_calories": 2278.4,
  "macros": {
    "protein_g": 164.0,
    "carbs_g": 258.0,
    "fat_g": 65.6
  }
}
```

This endpoint intentionally does not return micronutrients.

## Micronutrient Targets

The micronutrient endpoint requires a bearer token and reads the authenticated user's saved profile. If the user has no profile, it returns `PROFILE_NOT_FOUND`.

Supported nutrients:

- `fiber`
- `calcium`
- `iron`
- `magnesium`
- `potassium`
- `sodium`
- `vitamin_a`
- `vitamin_c`
- `vitamin_d`
- `vitamin_b12`
- `folate`

Reference strategy:

- MVP values are centralized in `app/nutrition/micronutrients.py`.
- Values are based on National Academies Dietary Reference Intakes as surfaced through NIH Office of Dietary Supplements fact sheets, plus the National Academies sodium/potassium DRI report and fiber DRI summary.
- Age and sex choose the matching reference row.
- Targets include `target_type` such as `RDA` or `AI`.
- Upper limits are included where established or where a sodium CDRR applies.
- Some upper limits have scope notes: magnesium applies to supplemental magnesium only, vitamin A applies to preformed vitamin A, and folate applies to synthetic folic acid from fortified foods or supplements.

Get micronutrient targets:

```bash
curl http://127.0.0.1:8000/api/v1/nutrition/micronutrients \
  -H "Authorization: Bearer <access_token>"
```

Expected targets for a saved profile with `age = 29` and `sex = male`:

| Code | Target | Unit | Upper limit |
|---|---:|---|---:|
| `fiber` | 38 | g | null |
| `calcium` | 1000 | mg | 2500 |
| `iron` | 8 | mg | 45 |
| `magnesium` | 400 | mg | 350 |
| `potassium` | 3400 | mg | null |
| `sodium` | 1500 | mg | 2300 |
| `vitamin_a` | 900 | mcg RAE | 3000 |
| `vitamin_c` | 90 | mg | 2000 |
| `vitamin_d` | 15 | mcg | 100 |
| `vitamin_b12` | 2.4 | mcg | null |
| `folate` | 400 | mcg DFE | 1000 |

Current limitations:

- Pregnancy and lactation-specific targets are not modeled.
- Micronutrient targets are persisted as meal-plan snapshots when a daily plan is generated, but standalone target-set history is not implemented yet.
- Meal validation is not implemented yet.

## Food Database

Food endpoints require a bearer token.

The internal food database stores food metadata in `foods`, nutrient values in `food_nutrients`, and serving-to-gram conversions in `food_servings`.

Nutrition values are normalized per 100 grams. Serving rows only convert human serving labels such as `1 cup`, `1 tbsp`, `1 medium`, or `1 piece` into grams; they do not duplicate nutrition facts.

Supported food sources:

- `internal`
- `usda`
- `licensed`

Current nutrient code strategy:

- `calories`
- `protein`
- `carbohydrates`
- `fat`
- `fiber`
- `calcium`
- `iron`
- `magnesium`
- `potassium`
- `sodium`
- `vitamin_a`
- `vitamin_c`
- `vitamin_d`
- `vitamin_b12`
- `folate`

Seed development foods:

```bash
python -m app.scripts.seed_foods
```

The seed command is idempotent. It uses `source = internal` and stable `source_food_id` values, and updates the same development fixture foods if run again.

Seed data includes Chicken Breast, Cooked Rice, Egg, Oats, Milk, Greek Yogurt, Spinach, Broccoli, Banana, Salmon, Olive Oil, and Potato.

These values are development/test fixtures with approximate nutrition per 100g. They are not production USDA data.

List foods:

```bash
curl http://127.0.0.1:8000/api/v1/foods \
  -H "Authorization: Bearer <access_token>"
```

Search foods:

```bash
curl "http://127.0.0.1:8000/api/v1/foods?search=chicken" \
  -H "Authorization: Bearer <access_token>"
```

Filter foods:

```bash
curl "http://127.0.0.1:8000/api/v1/foods?category=protein" \
  -H "Authorization: Bearer <access_token>"
```

Get food detail:

```bash
curl http://127.0.0.1:8000/api/v1/foods/<food_id> \
  -H "Authorization: Bearer <access_token>"
```

## USDA FoodData Central

USDA endpoints require a bearer token and a configured `USDA_API_KEY`.

Search USDA foods:

```bash
curl "http://127.0.0.1:8000/api/v1/foods/usda/search?q=chicken&page_size=10&page=1" \
  -H "Authorization: Bearer <access_token>"
```

Search returns Kcalm-shaped summary records and does not persist results automatically.

Import one USDA food by FDC ID:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/foods/usda/import/<fdc_id> \
  -H "Authorization: Bearer <access_token>"
```

Duplicate behavior:

- USDA food identity is `source = usda` plus `source_food_id = <fdc_id>`.
- If a USDA food was already imported, the import endpoint returns the existing local food with `status = existing` and does not create duplicate rows.
- New imports return `status = imported`.

Nutrient mapping:

- USDA nutrient IDs and names are centralized in `app/integrations/usda_nutrients.py`.
- Supported imported nutrient codes are the same MVP food nutrient codes listed above.
- Unit conversion is deterministic for compatible units such as `kcal`, `g`, `mg`, and `mcg`.
- Unsupported units are skipped rather than guessed.

Normalization:

- Kcalm stores nutrients per 100g.
- The importer uses USDA `foodNutrients` amounts as the per-100g source and does not import serving-based `labelNutrients`.
- USDA household portions are imported only when a reliable gram weight is present.
- A `100 g` serving is added consistently for imported USDA foods.

Current USDA limitations:

- No USDA bulk import, scheduled sync, or import batch tracking yet.
- No USDA data is fetched during nutrition calculation or meal planning.
- Meal generation uses already-imported structured local foods and recipe nutrition snapshots.

## Recipe Database

Recipe endpoints require a bearer token.

Recipes are structured records that reference existing local `Food` rows. Recipe ingredient nutrition is never entered manually by clients. The canonical calculation quantity is `quantity_grams`.

Nutrition formula:

```text
ingredient nutrient = food nutrient per 100g * ingredient quantity_grams / 100
recipe total = sum ingredient nutrients
per-serving = recipe total / recipe.servings
```

Calculated recipe nutrients are persisted in `recipe_nutrients` for future solver-readiness and recalculated transactionally whenever ingredients or serving count change.

Missing nutrient behavior:

- Kcalm sums known FoodNutrient values.
- If an ingredient lacks a supported nutrient row, the recipe nutrient is marked `complete = false`.
- `missing_ingredient_count` identifies how many ingredients did not provide that nutrient.
- Missing values are not invented.

Time and serving behavior:

- `servings` is the number of portions the full recipe produces.
- `total_time_minutes` is derived as `prep_time_minutes + cook_time_minutes`.
- Recipes tagged `quick` must have `total_time_minutes <= 20`.
- Recipe steps support `phase`, `duration_seconds`, `timer_required`, `timer_seconds`, and nullable `cue_action`, `animation_key`, `media_asset_key`, and `visual_cue` metadata for future recipe-player clients.
- `duration_seconds` is a step estimate; `timer_seconds` is an explicit timer duration and is not assumed to equal the step duration.

Tags and equipment:

- Tags are explicit structured values such as `quick`, `breakfast`, `lunch`, `dinner`, `snack`, `vegetarian`, `vegan`, `dairy_free`, `gluten_free`, and `high_protein`.
- Equipment is stored as explicit per-recipe requirements using the current profile vocabulary style: `oven`, `stovetop`, `microwave`, `blender`, and `air_fryer`.
- Dietary safety is not inferred from recipe names.

Seed development recipes:

```bash
python -m app.scripts.seed_recipes
```

The recipe seed command is idempotent and also ensures development food seed data exists. Seed recipes are development/test fixtures, not a licensed production recipe database.

Recipe endpoints:

```bash
curl http://127.0.0.1:8000/api/v1/recipes \
  -H "Authorization: Bearer <access_token>"

curl "http://127.0.0.1:8000/api/v1/recipes?search=chicken" \
  -H "Authorization: Bearer <access_token>"

curl "http://127.0.0.1:8000/api/v1/recipes?tag=quick" \
  -H "Authorization: Bearer <access_token>"

curl "http://127.0.0.1:8000/api/v1/recipes?max_total_time_minutes=20" \
  -H "Authorization: Bearer <access_token>"
```

Create recipe:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recipes \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Chicken Rice Bowl",
    "description": "Simple high-protein bowl.",
    "servings": 2,
    "prep_time_minutes": 5,
    "cook_time_minutes": 10,
    "difficulty": "easy",
    "ingredients": [
      {
        "food_id": "<chicken_food_id>",
        "quantity_grams": 100,
        "display_quantity": "100",
        "display_unit": "g",
        "position": 1
      },
      {
        "food_id": "<rice_food_id>",
        "quantity_grams": 100,
        "display_quantity": "100",
        "display_unit": "g",
        "position": 2
      }
    ],
    "steps": [
      {
        "position": 1,
        "instruction": "Warm the chicken.",
        "phase": "cook",
        "duration_seconds": 120,
        "timer_required": true,
        "timer_seconds": 120
      },
      {
        "position": 2,
        "instruction": "Serve over rice.",
        "phase": "serve",
        "duration_seconds": 60
      }
    ],
    "tags": ["lunch", "quick", "high_protein"],
    "equipment": ["stovetop"]
  }'
```

Patch recipe:

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/recipes/<recipe_id> \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"servings":4}'
```

Archive recipe:

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/recipes/<recipe_id> \
  -H "Authorization: Bearer <access_token>"
```

## Recipe Candidate Filtering

Candidate filtering prepares solver-ready recipes without running optimization. The preview endpoint requires a bearer token and reads the authenticated user's saved profile. If the user has no saved profile, it returns `PROFILE_NOT_FOUND`.

Flow:

```text
User Profile -> request constraints -> recipe candidate filtering -> preview response
```

Hard constraints:

- Active recipes only; archived recipes are excluded.
- Optional `meal_type` must match one of the explicit recipe tags: `breakfast`, `lunch`, `dinner`, or `snack`.
- Time uses request `max_total_time_minutes` when provided, otherwise the profile's `max_cooking_minutes`.
- Recipe equipment requirements must be a subset of profile equipment.
- Supported dietary restrictions use explicit tags: `vegetarian`, `vegan`, `dairy_free`, `gluten_free`, `pescatarian`, and `halal`.
- `excluded_recipe_ids`, `required_tags`, and `excluded_tags` are hard filters.
- `require_complete_nutrition` filters out recipes with missing required nutrient data. If `required_nutrient_codes` is empty, all supported recipe nutrients are required.
- Disliked foods use conservative exact food-name matching against recipe ingredients.

Soft preferences:

- Preferred foods are returned as metadata only.
- Candidate filtering does not rank, score, or optimize candidates.

Allergy limitation:

- Allergy filtering uses reviewed food allergen metadata and excludes unknown/unreviewed ingredients. Supported-code coverage is reported by `allergy_filtering_supported`; this is not a cross-contact or medical safety guarantee.
- The service does not infer allergens from names or ingredient text.

Rejection reason codes:

- `inactive`
- `explicitly_excluded`
- `wrong_meal_type`
- `missing_required_tag`
- `excluded_tag`
- `exceeds_time_limit`
- `missing_required_equipment`
- `dietary_restriction_mismatch`
- `allergy_conflict`, `allergy_metadata_missing`, `unsupported_allergy`
- `disliked_food`
- `incomplete_nutrition`

Candidate preview:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recipes/candidates/preview \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "meal_type": "lunch",
    "max_total_time_minutes": 20,
    "require_complete_nutrition": true,
    "required_nutrient_codes": ["calories", "protein"],
    "excluded_recipe_ids": [],
    "required_tags": ["quick"],
    "excluded_tags": []
  }'
```

## OR-Tools Daily Solver Preview

The daily solver preview chooses a one-day combination from eligible recipe candidates. It does not persist a meal plan.

Pipeline:

```text
User Profile + Targets
        ->
Recipe Candidate Filtering
        ->
Eligible Candidate DTOs
        ->
OR-Tools CP-SAT Solver
        ->
Non-persisted Daily Plan Result
```

Architecture:

- Route: `POST /api/v1/meal-plans/solve/preview`
- API/service orchestration: `app/services/meal_solver_service.py`
- OR-Tools model: `app/meal_planning/solver.py`
- Integer scaling helpers: `app/meal_planning/scaling.py`
- The solver receives candidate DTOs and never queries arbitrary recipes directly.
- Nutrition targets are calculated from the authenticated user's saved profile because persisted target sets are not implemented yet.

Default meal slot rule:

- `breakfast`: required, exactly 1 recipe
- `lunch`: required, exactly 1 recipe
- `dinner`: required, exactly 1 recipe
- `snack`: optional, 0 or 1 recipe

Clients may override `meal_slots` for testing. Meal type comes from recipe tags only; names are not inferred.

Portion strategy:

- MVP solver portions are fixed at `1.0` recipe serving per selected meal.
- Arbitrary floating serving sizes are not used.
- Discrete portion multipliers are deferred to the next solver expansion.

Nutrition source:

```text
FoodNutrient -> RecipeIngredient quantity -> RecipeNutrient -> candidate -> solver
```

The solver uses per-serving recipe nutrition already calculated by deterministic backend code. It does not call USDA, OpenAI, or text-derived nutrition.

Integer scaling:

- OR-Tools operates on integers.
- Nutrients stay in their native units: `kcal`, `g`, `mg`, or `mcg` variants.
- Values are scaled by `1000`, preserving thousandths of the native unit.
- Scaling uses decimal half-up rounding.

Objective:

- Nutrition bands are optimized as penalties, not hard constraints.
- The objective minimizes normalized deviation for calories, protein, carbohydrates, and fat.
- Micronutrients add shortfall penalties.
- Applicable upper limits add excess penalties for true `UL` and `CDRR` targets.
- Tie-breaking is deterministic by candidate/slot order.

Tolerance and status:

- Calories and macros report `within_tolerance`, `below_tolerance`, or `above_tolerance`.
- Preferred tolerance is +/- 5%.
- The solver can still return the closest structurally valid plan when the preferred nutrition band is impossible.
- `within_preferred_tolerance` is true only when calories/macros are within tolerance and micronutrient goals/upper limits are satisfied.

Solver behavior:

- OR-Tools CP-SAT timeout defaults to 3 seconds.
- Search uses one worker and a fixed seed for stable behavior.
- Status values are `optimal`, `feasible`, and `infeasible`.
- Timeout with a feasible OR-Tools result returns `feasible`.
- Missing required slots, no candidates, malformed candidate nutrition, and invalid targets are controlled outcomes/errors, not HTTP 500s.
- The same recipe cannot fill multiple meal slots in the same day.

Preview request:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans/solve/preview \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "meal_slots": [
      {"meal_type": "breakfast", "required": true},
      {"meal_type": "lunch", "required": true},
      {"meal_type": "dinner", "required": true},
      {"meal_type": "snack", "required": false}
    ],
    "max_total_time_minutes": 60,
    "require_complete_nutrition": true,
    "required_nutrient_codes": [],
    "excluded_recipe_ids": [],
    "required_tags": [],
    "excluded_tags": [],
    "solver_time_limit_seconds": 3
  }'
```

Restrictive infeasible example:

```json
{
  "meal_slots": [
    {
      "meal_type": "dinner",
      "required": true
    }
  ],
  "required_tags": ["vegetarian"],
  "require_complete_nutrition": true
}
```

Expected controlled response shape:

```json
{
  "status": "infeasible",
  "meals": [],
  "infeasibility_reasons": ["missing_meal_slot_candidate:dinner"]
}
```

## Daily Meal Plan Persistence

Persisted one-day meal plans use the same deterministic solver path as the preview endpoint, then store the generated result transactionally.

Pipeline:

```text
User Profile + Targets
        ->
Recipe Candidate Filtering
        ->
OR-Tools CP-SAT Solver
        ->
Nutrition Validation Metadata
        ->
Meal Plan Snapshot Rows
```

Architecture:

- Create route: `POST /api/v1/meal-plans`
- List route: `GET /api/v1/meal-plans`
- Detail route: `GET /api/v1/meal-plans/{meal_plan_id}`
- Archive route: `DELETE /api/v1/meal-plans/{meal_plan_id}`
- Persistence orchestration: `app/services/meal_plan_service.py`
- Solver orchestration remains in `app/services/meal_solver_service.py`

Plan creation request fields match the solver preview request plus optional `plan_date`.

If `plan_date` is omitted, the backend uses the current UTC date. A user may have only one active `generated` plan per date. Duplicate generated plans return `PLAN_ALREADY_EXISTS` with HTTP `409`.

Persisted snapshots:

- Recipe name at generation time.
- Selected meal type.
- Selected serving amount.
- Per-item nutrient contribution amounts.
- Calorie, protein, carbohydrate, and fat targets.
- Micronutrient target, minimum, upper-limit, and unit metadata.
- Solver status, objective value, solve time, candidate count, and preferred-tolerance flag.

Read responses reconstruct `daily_totals`, macro deviations, and micronutrient coverage from the persisted snapshots, not from mutable recipe or profile rows.

Create a daily plan:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "plan_date": "2026-10-03",
    "meal_slots": [
      {"meal_type": "breakfast", "required": true},
      {"meal_type": "lunch", "required": true},
      {"meal_type": "dinner", "required": true},
      {"meal_type": "snack", "required": false}
    ],
    "max_total_time_minutes": 60,
    "require_complete_nutrition": true,
    "required_nutrient_codes": [],
    "excluded_recipe_ids": [],
    "required_tags": [],
    "excluded_tags": [],
    "solver_time_limit_seconds": 3
  }'
```

Get a plan:

```bash
curl http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id> \
  -H "Authorization: Bearer <access_token>"
```

List generated plans:

```bash
curl "http://127.0.0.1:8000/api/v1/meal-plans?plan_date=2026-10-03" \
  -H "Authorization: Bearer <access_token>"
```

List archived plans:

```bash
curl "http://127.0.0.1:8000/api/v1/meal-plans?status=archived" \
  -H "Authorization: Bearer <access_token>"
```

Archive a plan:

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id> \
  -H "Authorization: Bearer <access_token>"
```

Controlled errors:

- `PROFILE_NOT_FOUND`: authenticated user has no saved profile.
- `MEAL_PLAN_INFEASIBLE`: solver could not produce a persisted plan; no meal-plan rows are written.
- `PLAN_ALREADY_EXISTS`: generated plan already exists for the user and date.
- `MEAL_PLAN_NOT_FOUND`: plan does not exist or belongs to another user.
- `MEAL_PLAN_SAVE_FAILED`: persistence failed after solving; the transaction is rolled back.

Current limitations:

- Daily plan endpoints persist one-day plans only.
- Status values are `generated` and `archived`; confirm/accept states are deferred.
- Portions remain fixed at `1.0` recipe serving.
- Full-day regeneration and AI explanations are not implemented yet.

## Weekly Plan Generation / Grocery Foundation

Weekly planning creates a seven-day container and reuses the existing daily plan generation path for each calendar date.

Pipeline:

```text
Weekly Request
        ->
Existing Daily Candidate Filtering
        ->
Existing Daily OR-Tools Solver
        ->
Persisted Daily Meal Plans
        ->
WeeklyMealPlan container
        ->
Meal item ingredient snapshots
        ->
Grocery preview aggregation
```

Week semantics:

- `start_date` may be any calendar date.
- `end_date` is derived as `start_date + 6 days`.
- The API creates exactly seven daily plans.
- Weekly creation is fully atomic: if any day cannot be generated, the week and newly generated daily plans are rolled back.

Duplicate and conflict behavior:

- A user can have one active `generated` weekly plan for the same `start_date`/`end_date`.
- Duplicate active weeks return `409 WEEKLY_PLAN_ALREADY_EXISTS`.
- Existing active generated daily plans inside the requested date range are not overwritten and return `409 DAILY_PLAN_ALREADY_EXISTS_FOR_WEEK`.

Variety behavior:

- The weekly orchestrator tries to exclude the previous day's selected recipe IDs when generating the next day.
- This avoids adjacent-day exact recipe repetition when alternatives exist.
- If that variety exclusion makes a day infeasible, the day is retried without the variety exclusion so limited catalogs can still produce a week.

Ingredient snapshot strategy:

- Daily plan creation now stores `meal_plan_item_ingredients`.
- Snapshot quantity uses:

```text
recipe_ingredient.quantity_grams * meal_plan_item.servings
```

- Grocery previews aggregate these persisted snapshots, not live recipe ingredients.
- Recipe edits after plan creation do not change an existing weekly grocery preview.
- Older or manually associated plans without ingredient snapshots return `409 GROCERY_SNAPSHOT_MISSING`.

Create a weekly plan:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/weekly-meal-plans \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2026-10-12",
    "meal_slots": [
      {"meal_type": "breakfast", "required": true},
      {"meal_type": "lunch", "required": true},
      {"meal_type": "dinner", "required": true},
      {"meal_type": "snack", "required": false}
    ],
    "max_total_time_minutes": 60,
    "require_complete_nutrition": true,
    "required_nutrient_codes": [],
    "excluded_recipe_ids": [],
    "required_tags": [],
    "excluded_tags": [],
    "solver_time_limit_seconds": 3
  }'
```

Get a weekly plan:

```bash
curl http://127.0.0.1:8000/api/v1/weekly-meal-plans/<weekly_plan_id> \
  -H "Authorization: Bearer <access_token>"
```

List weekly plans:

```bash
curl http://127.0.0.1:8000/api/v1/weekly-meal-plans \
  -H "Authorization: Bearer <access_token>"
```

Archive a weekly plan:

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/weekly-meal-plans/<weekly_plan_id> \
  -H "Authorization: Bearer <access_token>"
```

Archiving a weekly plan also archives the generated member daily plans. It does not touch unrelated standalone daily plans.

Preview weekly grocery aggregation:

```bash
curl http://127.0.0.1:8000/api/v1/weekly-meal-plans/<weekly_plan_id>/grocery/preview \
  -H "Authorization: Bearer <access_token>"
```

Example grocery preview response:

```json
{
  "weekly_plan_id": "00000000-0000-0000-0000-000000000000",
  "start_date": "2026-10-12",
  "end_date": "2026-10-18",
  "items": [
    {
      "food_id": "00000000-0000-0000-0000-000000000001",
      "food_name": "Chicken Breast",
      "total_grams": 350.0,
      "source": "internal",
      "source_food_id": "dev_chicken_breast",
      "category": "protein"
    }
  ]
}
```

Current limitations:

- Weekly planning reuses daily targets and does not create separate weekly nutrition targets.
- Portion choices remain fixed at `1.0` selected serving until the solver portion milestone.

## Smart Grocery List

Smart grocery lists persist the weekly grocery preview into editable list rows. Generation is deterministic and does not call USDA, OpenAI, delivery services, or live recipe ingredients.

Pipeline:

```text
WeeklyMealPlan
        ->
Persisted meal_plan_item_ingredients
        ->
Grocery aggregation by food_id
        ->
GroceryList
        ->
Editable GroceryListItem rows
```

Generation behavior:

- Create a list with `POST /api/v1/weekly-meal-plans/<weekly_plan_id>/grocery-list`.
- Users can create lists only for their own weekly plans.
- Archived weekly plans cannot create new grocery lists.
- One active grocery list is allowed per weekly plan; a duplicate active create returns `409 GROCERY_LIST_ALREADY_EXISTS`.
- Automatic item quantities are canonical grams using `quantity`, `unit: "g"`, and `quantity_grams`.
- Aggregation identity is stable `food_id`, so repeated food IDs merge and different foods with the same display name remain separate.
- Each generated item stores `food_name_snapshot`; later food or recipe edits do not change existing grocery list rows.

Category behavior:

- Kcalm uses deterministic grocery categories, not LLM classification.
- Known food categories are mapped centrally: fruit/vegetable/starchy_vegetable -> `produce`, protein -> `meat_seafood`, dairy -> `dairy`, grain/grains -> `grains`, fat/pantry -> `pantry`, frozen -> `frozen`.
- Unknown categories fall back to `other`.
- Store-specific aisle ordering is deferred.

Editable list behavior:

- `GET /api/v1/grocery-lists` lists active lists by default and supports `weekly_plan_id` and `status` filters.
- `GET /api/v1/grocery-lists/<grocery_list_id>` returns full list details.
- `PATCH /api/v1/grocery-lists/<grocery_list_id>/items/<item_id>` updates checked state, quantity, unit, or category without changing the weekly plan.
- `POST /api/v1/grocery-lists/<grocery_list_id>/items` adds a manual item with `manually_added: true` and no required `food_id`.
- `DELETE /api/v1/grocery-lists/<grocery_list_id>/items/<item_id>` permanently removes an item from that list.
- `POST /api/v1/grocery-lists/<grocery_list_id>/regenerate` rebuilds automatic items from the persisted weekly snapshots, preserves manual items, preserves generated checked state by Food ID, and resets generated quantities back to snapshot totals.
- `DELETE /api/v1/grocery-lists/<grocery_list_id>` soft-archives the list; archived lists are hidden from the default listing.

Generate a grocery list:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/weekly-meal-plans/<weekly_plan_id>/grocery-list \
  -H "Authorization: Bearer <access_token>"
```

Get a grocery list:

```bash
curl http://127.0.0.1:8000/api/v1/grocery-lists/<grocery_list_id> \
  -H "Authorization: Bearer <access_token>"
```

List active grocery lists:

```bash
curl http://127.0.0.1:8000/api/v1/grocery-lists \
  -H "Authorization: Bearer <access_token>"
```

Check an item:

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/grocery-lists/<grocery_list_id>/items/<item_id> \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"checked": true}'
```

Add a manual item:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/grocery-lists/<grocery_list_id>/items \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Sparkling Water", "quantity": 2, "unit": "bottle", "category": "other"}'
```

Regenerate automatic items:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/grocery-lists/<grocery_list_id>/regenerate \
  -H "Authorization: Bearer <access_token>"
```

Current limitations:

- Household unit conversion and store-specific aisle grouping are deferred.
- Regeneration uses only the weekly plan's currently persisted daily plans and ingredient snapshots.
- Manual item deletion is permanent for the list item.
- Archived grocery lists cannot be modified.

## Meal Swap

Single-meal swap replaces one item inside an existing generated daily plan. The rest of the day remains locked and keeps its persisted nutrition snapshots.

Pipeline:

```text
Persisted Plan
        ->
Locked Meal Snapshots
        ->
Recipe Candidate Filtering
        ->
Existing OR-Tools Solver
        ->
Transactional Item Snapshot Update
```

Architecture:

- Route: `POST /api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/swap`
- Service: `app/services/meal_swap_service.py`
- Solver: existing `app/meal_planning/solver.py`
- Candidate filtering: existing `app/services/recipe_candidate_service.py`

Default behavior:

- The selected item is replaceable.
- All other meal-plan items are locked.
- The replacement must match the selected item's meal type.
- The current recipe and locked recipe IDs are excluded from replacement candidates.
- The plan's original target snapshots are used. Current profile target changes do not rewrite historical swap targets.
- Locked meal nutrition comes from `meal_plan_item_nutrients`, not current recipe rows.
- On success, only the selected item's recipe ID, recipe name snapshot, serving amount, and nutrient snapshots are updated.

Supported structured constraints:

- `max_total_time_minutes`
- `require_complete_nutrition`
- `required_tags`
- `excluded_tags`
- `excluded_recipe_ids`
- `solver_time_limit_seconds`

Unsupported constraints:

- `different_protein`: deferred until recipes have reliable structured protein-source metadata.
- `eating_out`: deferred until restaurant/external meal data exists.
- Natural-language swap parsing is available through the guarded `ai-swap` endpoint.

Controlled errors:

- `MEAL_PLAN_NOT_FOUND`: plan does not exist or belongs to another user.
- `MEAL_PLAN_ITEM_NOT_FOUND`: item does not belong to the plan.
- `MEAL_PLAN_ARCHIVED`: archived plans cannot be swapped.
- `NO_SWAP_CANDIDATE`: no eligible solver-valid replacement exists.
- `UNSUPPORTED_SWAP_CONSTRAINT`: unsupported structured constraint was requested.
- `MEAL_SWAP_SAVE_FAILED`: transactional persistence failed; the old plan remains unchanged.

Swap a meal:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/swap \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "max_total_time_minutes": 20,
    "required_tags": ["quick"],
    "excluded_tags": [],
    "excluded_recipe_ids": []
  }'
```

An unconstrained swap can use an empty JSON body:

```json
{}
```

Full-day regeneration is deferred for this milestone. The current implementation prioritizes correct single-meal replacement with locked snapshots and preserved target snapshots.

## Adaptive Logging / Ate-as-Planned Tracking

Meal logging records actual intake separately from planned meal snapshots. Logs never overwrite `meal_plan_item_nutrients`, target snapshots, recipes, foods, or original plan totals.

Architecture:

```text
Persisted Meal Plan
        ->
Planned Meal Snapshot
        ->
User Logs Intake
        ->
Actual Nutrition Snapshot
        ->
Planned-vs-Actual Summary
```

Supported log types:

- `ate_as_planned`: copies the persisted `meal_plan_item_nutrients` snapshot exactly.
- `corrected` with `source_type: "food"`: calculates from local `food_nutrients` per 100g and `quantity_grams`.
- `corrected` with `source_type: "recipe"`: calculates from saved `recipe_nutrients.per_serving_amount` and `servings`.

Behavior:

- `POST /api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/log` creates or updates the current active log for that meal item.
- Re-logging the same item updates the existing active log row and replaces actual nutrient snapshots transactionally.
- `DELETE /api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/log` removes the current actual log and leaves planned snapshots unchanged.
- `GET /api/v1/meal-plans/<meal_plan_id>/actual-summary` returns planned totals, actual logged totals, target snapshots, actual-vs-planned differences, actual-vs-target differences, known/missing actual target nutrients, and adherence metadata.
- Archived plans cannot receive new logs or resets and return `MEAL_PLAN_ARCHIVED`.
- Users can only log items on their own plans; other users receive non-leaking not-found errors.

Adherence:

- `planned_meals_count` is the number of persisted meal-plan items.
- `logged_meals_count` is the number of active meal logs.
- `ate_as_planned_count` counts active logs with `type: "ate_as_planned"`.
- `corrected_count` counts active corrected logs.
- `adherence_percent = ate_as_planned_count / planned_meals_count * 100`.

Missing nutrient behavior:

- Corrected food logs persist only nutrients present in local `food_nutrients`.
- Corrected recipe logs use the current structured `recipe_nutrients` rows at log time.
- Missing nutrient values are not invented; response metadata lists missing nutrient codes relative to the tracked nutrient set.

Ate as planned:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/log \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"type": "ate_as_planned"}'
```

Correct with food:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/log \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"type": "corrected", "source_type": "food", "food_id": "<food_id>", "quantity_grams": 180}'
```

Correct with recipe:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/log \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"type": "corrected", "source_type": "recipe", "recipe_id": "<recipe_id>", "servings": 1.5}'
```

Get planned-vs-actual summary:

```bash
curl http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id>/actual-summary \
  -H "Authorization: Bearer <access_token>"
```

Reset a log:

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/log \
  -H "Authorization: Bearer <access_token>"
```

Current limitations:

- Full-day regeneration from the same day's target snapshots is deferred.
- Free-text, barcode, photo, restaurant, and wearable logging are deferred.
- Full revision history is deferred; the MVP keeps one active/current log per meal-plan item.

## Adaptive Next-Day Compensation / Regeneration

Adaptive next-day planning uses yesterday's persisted target snapshots and actual intake logs to adjust tomorrow's target conservatively. It does not mutate yesterday's plan, target snapshots, meal items, or logs.

Pipeline:

```text
Previous persisted meal plan
        ->
Actual intake logs
        ->
Actual minus source target deviation
        ->
Safe compensation policy
        ->
Adjusted next-day target DTO
        ->
Existing candidate filtering
        ->
Existing OR-Tools daily solver
        ->
New persisted daily plan
```

Source log requirement:

- Every persisted meal-plan item on the source day must have an active log.
- Unlogged meals are not assumed eaten.
- Missing or partial logs return `INCOMPLETE_DAILY_LOG`.
- Actual macro data must include valid `calories`, `protein`, `carbohydrates`, and `fat`; malformed actual snapshots return `ACTUAL_LOG_NUTRITION_INCOMPLETE`.

Compensation policy:

- Policy version: `adaptive_v1`.
- `compensation_fraction = 0.25`.
- Overage lowers tomorrow's target by 25% of the previous-day calorie overage.
- Under-eating raises tomorrow's target by 25% of the previous-day calorie shortfall.
- Adjustment is capped to the smaller of `250 kcal` or `10%` of the source calorie target.
- Adjusted calories cannot go below `1200 kcal`.
- Protein and fat targets are preserved as anchors; carbohydrates fill the remaining adjusted calories.
- Micronutrient deviations are reported, but next-day micronutrient targets stay unchanged for MVP safety.

Routes:

- Preview: `POST /api/v1/meal-plans/<source_plan_id>/adaptive-preview`
- Generate: `POST /api/v1/meal-plans/<source_plan_id>/generate-next-day`

Both endpoints accept the same optional constraint body as the daily solver preview: `meal_slots`, `max_total_time_minutes`, `require_complete_nutrition`, `required_nutrient_codes`, `excluded_recipe_ids`, `required_tags`, `excluded_tags`, and `solver_time_limit_seconds`.

Preview example:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans/<source_plan_id>/adaptive-preview \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Generate next day:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans/<source_plan_id>/generate-next-day \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Conflict behavior:

- The generated plan date is `source_plan.plan_date + 1 day`.
- If an active generated plan already exists for that next day, the API returns `PLAN_ALREADY_EXISTS`.
- Adaptive generation is transactional; if meal items or adaptation metadata cannot be saved, the new plan is rolled back and the source plan/logs remain unchanged.

Metadata:

- Generated adaptive plans persist one `meal_plan_adaptations` snapshot row.
- The snapshot stores the source plan ID, policy version, base target, actual calories, calorie deviation, compensation amount, adjusted calorie target, macro targets, and whether a safety cap applied.

Current limitations:

- Full same-day regeneration is deferred.
- Micronutrient deficits/overages are not carried forward into hard targets.
- Free-text, barcode, photo, restaurant, wearable, grocery delivery, and AI-driven adaptation are deferred.

## Recipe Execution / Recipe Player Foundation

Recipe execution endpoints provide deterministic step-by-step cooking data for a future mobile recipe player. The backend stores execution state and immutable snapshots, but it does not render animations, generate video, run countdown jobs, infer timers with AI, or log the meal as eaten.

Snapshot flow:

```text
Recipe or MealPlanItem
        ->
Execution session start
        ->
Immutable recipe name, serving, ingredient, equipment, and step snapshots
        ->
Step progress and timer metadata
        ->
Complete or abandon
```

Recipe step metadata:

- `phase`: `prep`, `cook`, `rest`, `assemble`, or `serve`.
- `duration_seconds`: estimated step duration.
- `timer_required`: copied from the structured recipe step timer flag.
- `timer_seconds`: explicit timer duration when available.
- `cue_action`, `animation_key`, `media_asset_key`, and `visual_cue`: nullable placeholders for future client media/animation handling.

Timer semantics:

- `duration_seconds` and `timer_seconds` are separate fields.
- The backend only persists explicit timer metadata.
- No server-side countdown worker runs; the client displays countdowns from the returned duration/state.

Routes:

- `POST /api/v1/recipes/<recipe_id>/execution-sessions`
- `POST /api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/execution-session`
- `GET /api/v1/recipe-execution-sessions/<session_id>`
- `PATCH /api/v1/recipe-execution-sessions/<session_id>/progress`
- `POST /api/v1/recipe-execution-sessions/<session_id>/steps/<step_index>/complete`
- `POST /api/v1/recipe-execution-sessions/<session_id>/complete`
- `POST /api/v1/recipe-execution-sessions/<session_id>/abandon`

Start direct recipe execution:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recipes/<recipe_id>/execution-sessions \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"servings":1.0}'
```

Start from a meal-plan item:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/execution-session \
  -H "Authorization: Bearer <access_token>"
```

Progress:

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/recipe-execution-sessions/<session_id>/progress \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"current_step_index":1}'
```

Complete or abandon:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recipe-execution-sessions/<session_id>/complete \
  -H "Authorization: Bearer <access_token>"

curl -X POST http://127.0.0.1:8000/api/v1/recipe-execution-sessions/<session_id>/abandon \
  -H "Authorization: Bearer <access_token>"
```

Execution rules:

- Direct starts require an active recipe and positive servings.
- Meal-plan-item starts verify plan ownership and use the persisted meal-plan item recipe name, servings, and ingredient snapshots where available.
- A user can resume an `in_progress` session by reading it again.
- Completed and abandoned sessions are historical records and cannot be progressed.
- Only one active execution session is allowed per meal-plan item; completed or abandoned history remains.
- Recipe edits after session start do not change existing execution snapshots.

Current limitations:

- Step-level ingredient/equipment mapping is not modeled yet; the response includes recipe/session-level ingredient and equipment summaries and empty per-step references.
- Starting from a meal-plan item still reads current recipe steps because meal plans do not yet snapshot recipe steps before execution starts.
- Execution completion does not automatically create meal logs.
- Voice, TTS, camera recognition, smart appliances, wearable integration, delivery, restaurant matching, and frontend animation rendering are deferred.

## AI Assistance / Natural-Language Constraints

Kcalm uses OpenAI only as a language interpretation layer. AI output is validated, normalized, and then passed into existing deterministic services. AI never calculates nutrition, chooses final meals, bypasses candidate filtering, replaces OR-Tools, or writes directly to meal plans.

Configuration:

```text
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
OPENAI_TIMEOUT_SECONDS=10
```

Architecture:

```text
Natural language
        ->
OpenAI structured interpretation
        ->
Pydantic validation
        ->
Kcalm canonical tag and food resolver
        ->
Existing candidate filtering
        ->
Existing OR-Tools / swap service where applicable
```

Endpoints:

- `POST /api/v1/ai/constraints/interpret`
- `POST /api/v1/ai/meal-options`
- `POST /api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/ai-swap`

Supported structured intents:

- Meal type: `breakfast`, `lunch`, `dinner`, `snack`.
- Time: explicit numeric limits such as `15 minutes`.
- Tags: `quick`, `vegetarian`, `vegan`, `dairy_free`, `gluten_free`, `high_protein`.
- Food avoidance phrases such as `no chicken`, resolved locally to known `Food` rows before recipe exclusions are created.
- Soft food preferences such as `with yogurt`, returned as metadata only.

Unsupported or safety-limited intents:

- `different_protein`
- restaurant/eating-out requests
- `low_fodmap`
- `keto`
- allergy claims such as peanut allergy
- unsupported medical diets

Allergy behavior:

- Allergy-like language is returned in `unsupported_constraints`.
- The backend does not infer allergen safety from recipe names or descriptions.

Ambiguity behavior:

- Ambiguous requests such as "make it lighter" return `clarification_required = true` and a concise question.
- AI swap refuses to mutate a plan until clarification is resolved.

Interpret example:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ai/constraints/interpret \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "I want a quick high protein dinner with no chicken"}'
```

AI meal options:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ai/meal-options \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "Give me a vegetarian lunch under 15 minutes"}'
```

AI swap:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/meal-plans/<meal_plan_id>/items/<meal_plan_item_id>/ai-swap \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "Give me something quicker and dairy free"}'
```

Current limitations:

- AI explanations are deferred.
- AI interaction audit persistence is deferred; the current milestone logs privacy-safe success/failure metadata only.
- Food avoidance uses conservative local Food resolution and returns controlled validation errors for unresolved or ambiguous foods.

## Postman

Use this environment variable:

```text
base_url = http://127.0.0.1:8000/api/v1
```

Before running the full MVP checklist locally, apply migrations and seed development data:

```bash
alembic upgrade head
python -m app.scripts.seed_foods
python -m app.scripts.seed_recipes
uvicorn app.main:app --reload
```

### MVP Postman Checklist

Use `Content-Type: application/json` for JSON bodies. After login, set `access_token` from the login response and send `Authorization: Bearer {{access_token}}` on protected requests.

1. Register/Login
   - `POST {{base_url}}/auth/register`
   - Body: `{"email":"postman-mvp@example.com","password":"StrongPassword123"}`
   - Expected: `201 Created`, response includes `id` and `email`.
   - `POST {{base_url}}/auth/login`
   - Body: `{"email":"postman-mvp@example.com","password":"StrongPassword123"}`
   - Expected: `200 OK`, response includes `access_token`.

2. Profile
   - `POST {{base_url}}/users/profile`
   - Body: sample profile from the User Profile section with equipment `["stovetop","oven","blender","microwave"]`.
   - Expected: `201 Created`, verify `age`, `sex`, `goal`, `equipment`.
   - `PATCH {{base_url}}/users/profile`
   - Body: `{"preferred_foods":["chicken","rice"],"max_cooking_minutes":60}`
   - Expected: `200 OK`, verify updated values.

3. Nutrition Targets
   - `POST {{base_url}}/nutrition/calculate`
   - Body: sample nutrition body below.
   - Expected: `200 OK`, verify `bmr`, `tdee`, `target_calories`, `macros`.
   - `GET {{base_url}}/nutrition/micronutrients`
   - Expected: `200 OK`, verify supported micronutrient codes and upper-limit fields.

4. Recipes
   - `GET {{base_url}}/foods?search=chicken`
   - Expected: `200 OK`, capture `chicken_food_id`.
   - `GET {{base_url}}/recipes`
   - Expected: `200 OK`, capture a `recipe_id`.
   - Optional USDA: `GET {{base_url}}/foods/usda/search?q=chicken&page_size=10&page=1`, then `POST {{base_url}}/foods/usda/import/{{fdc_id}}`.

5. Candidate Preview
   - `POST {{base_url}}/recipes/candidates/preview`
   - Body: `{"meal_type":"lunch","max_total_time_minutes":60,"require_complete_nutrition":true,"required_nutrient_codes":[],"excluded_recipe_ids":[],"required_tags":["quick"],"excluded_tags":[]}`
   - Expected: `200 OK`, verify `candidates`, `exclusion_summary`, `filter_order`, `unsupported_allergies`, and the ingredient-metadata-only allergy scope.

6. Daily Plan
   - `POST {{base_url}}/meal-plans`
   - Body: create-plan body below with a unique `plan_date`.
   - Expected: `201 Created`, capture `meal_plan_id` and a lunch `meal_plan_item_id`.
   - `GET {{base_url}}/meal-plans/{{meal_plan_id}}`
   - Expected: `200 OK`, verify saved meals, targets, totals, deviations.

7. Swap
   - `POST {{base_url}}/meal-plans/{{meal_plan_id}}/items/{{meal_plan_item_id}}/swap`
   - Body: `{"max_total_time_minutes":60,"required_tags":["quick"],"excluded_tags":[],"excluded_recipe_ids":[]}`
   - Expected: `200 OK`, verify the selected item changes and locked meals remain.

8. Weekly Plan
   - `POST {{base_url}}/weekly-meal-plans`
   - Body: same solver fields as daily plan with `start_date` instead of `plan_date`.
   - Expected: `201 Created`, capture `weekly_plan_id`, verify seven `daily_plans`.
   - `GET {{base_url}}/weekly-meal-plans/{{weekly_plan_id}}/grocery/preview`
   - Expected: `200 OK`, verify merged food rows from snapshots.

9. Grocery List
   - `POST {{base_url}}/weekly-meal-plans/{{weekly_plan_id}}/grocery-list`
   - Expected: `201 Created`, capture `grocery_list_id` and an item `id`.
   - `PATCH {{base_url}}/grocery-lists/{{grocery_list_id}}/items/{{item_id}}`
   - Body: `{"checked":true}`
   - Expected: `200 OK`, verify item checked.
   - `POST {{base_url}}/grocery-lists/{{grocery_list_id}}/items`
   - Body: `{"name":"Sparkling Water","quantity":2,"unit":"bottle","category":"other"}`
   - Expected: `201 Created`, capture manual item `id`.
   - `DELETE {{base_url}}/grocery-lists/{{grocery_list_id}}/items/{{manual_item_id}}`
   - Expected: `204 No Content`.

10. Meal Logging
    - `POST {{base_url}}/meal-plans/{{meal_plan_id}}/items/{{meal_plan_item_id}}/log`
    - Body: `{"type":"ate_as_planned"}`
    - Expected: `200 OK`, verify planned nutrients copied.
    - Correct one item with a structured food: `{"type":"corrected","source_type":"food","food_id":"{{chicken_food_id}}","quantity_grams":180}`
    - Expected: `200 OK`, verify actual nutrients are calculated from `food_nutrients`.

11. Actual Summary
    - `GET {{base_url}}/meal-plans/{{meal_plan_id}}/actual-summary`
    - Expected: `200 OK`, verify `planned_totals`, `actual_totals`, and `adherence`.

12. Adaptive Preview
    - Log every meal in the source plan first.
    - `POST {{base_url}}/meal-plans/{{meal_plan_id}}/adaptive-preview`
    - Body: `{}`
    - Expected: `200 OK`, verify `adjusted_targets` and `solver_preview`.

13. Generate Next Day
    - `POST {{base_url}}/meal-plans/{{meal_plan_id}}/generate-next-day`
    - Body: `{}`
    - Expected: `201 Created`, verify `plan.plan_date` is source date + 1 day.

14. AI Constraint Interpretation
    - `POST {{base_url}}/ai/constraints/interpret`
    - Body: `{"text":"Give me a quick dinner"}`
    - Expected: `200 OK`, verify `required_tags=["quick"]`.

15. AI Meal Options/Swap
    - `POST {{base_url}}/ai/meal-options`
    - Body: `{"text":"Show me quick lunch options"}`
    - Expected: `200 OK`, verify `interpretation` and `candidate_preview`.
    - `POST {{base_url}}/meal-plans/{{meal_plan_id}}/items/{{meal_plan_item_id}}/ai-swap`
    - Body: `{"text":"Swap this for something quick"}`
    - Expected: `200 OK` when a valid alternative exists, or a controlled AI/swap error when constraints are unsupported.

16. Recipe Execution Session
    - `POST {{base_url}}/meal-plans/{{meal_plan_id}}/items/{{meal_plan_item_id}}/execution-session`
    - Expected: `201 Created`, capture `session_id`, verify `steps`, `ingredients`, `progress`.
    - `PATCH {{base_url}}/recipe-execution-sessions/{{session_id}}/progress`
    - Body: `{"current_step_index":0}`
    - Expected: `200 OK`, verify `current_step_index`.

17. Complete Execution
    - `POST {{base_url}}/recipe-execution-sessions/{{session_id}}/complete`
    - Expected: `200 OK`, verify `status="completed"` and all step snapshots are completed.

Health request:

```text
GET {{base_url}}/health
```

Auth requests:

```text
POST {{base_url}}/auth/register
POST {{base_url}}/auth/login
GET {{base_url}}/auth/me
```

Nutrition calculation request:

```text
POST {{base_url}}/nutrition/calculate
```

Headers:

```text
Content-Type: application/json
Authorization: Bearer {{access_token}}
```

Body:

```json
{
  "age": 29,
  "sex": "male",
  "height_cm": 178,
  "weight_kg": 82,
  "activity_level": "moderate",
  "goal": "fat_loss",
  "target_rate": 0.5
}
```

Expected:

```json
{
  "bmr": 1792.5,
  "tdee": 2778.4,
  "target_calories": 2278.4,
  "macros": {
    "protein_g": 164.0,
    "carbs_g": 258.0,
    "fat_g": 65.6
  }
}
```

Micronutrient target request:

```text
GET {{base_url}}/nutrition/micronutrients
```

Headers:

```text
Authorization: Bearer {{access_token}}
```

Expected for the sample male age-29 profile:

```text
200 OK
```

Response includes all supported micronutrients listed above.

Food requests:

```text
GET {{base_url}}/foods
GET {{base_url}}/foods?search=chicken
GET {{base_url}}/foods?category=protein
GET {{base_url}}/foods/{{food_id}}
GET {{base_url}}/foods/usda/search?q=chicken
POST {{base_url}}/foods/usda/import/{{fdc_id}}
```

Recipe requests:

```text
GET {{base_url}}/recipes
POST {{base_url}}/recipes
POST {{base_url}}/recipes/candidates/preview
GET {{base_url}}/recipes/{{recipe_id}}
PATCH {{base_url}}/recipes/{{recipe_id}}
DELETE {{base_url}}/recipes/{{recipe_id}}
GET {{base_url}}/recipes?search=chicken
GET {{base_url}}/recipes?tag=quick
GET {{base_url}}/recipes?max_total_time_minutes=20
```

Recipe execution requests:

```text
POST {{base_url}}/recipes/{{recipe_id}}/execution-sessions
POST {{base_url}}/meal-plans/{{meal_plan_id}}/items/{{meal_plan_item_id}}/execution-session
GET {{base_url}}/recipe-execution-sessions/{{session_id}}
PATCH {{base_url}}/recipe-execution-sessions/{{session_id}}/progress
POST {{base_url}}/recipe-execution-sessions/{{session_id}}/steps/{{step_index}}/complete
POST {{base_url}}/recipe-execution-sessions/{{session_id}}/complete
POST {{base_url}}/recipe-execution-sessions/{{session_id}}/abandon
```

Start direct recipe execution body:

```json
{
  "servings": 1.0
}
```

Progress body:

```json
{
  "current_step_index": 1
}
```

Expected execution response includes `session_id`, recipe/meal-plan references, `status`, `current_step_index`, `required_equipment`, `ingredients`, `step_count`, `progress`, and ordered step snapshots with phase, duration, timer, completion, and media placeholder fields.

Meal solver preview request:

```text
POST {{base_url}}/meal-plans/solve/preview
```

Headers:

```text
Authorization: Bearer {{access_token}}
Content-Type: application/json
```

Body:

```json
{
  "meal_slots": [
    {
      "meal_type": "breakfast",
      "required": true
    },
    {
      "meal_type": "lunch",
      "required": true
    },
    {
      "meal_type": "dinner",
      "required": true
    },
    {
      "meal_type": "snack",
      "required": false
    }
  ],
  "max_total_time_minutes": 60,
  "require_complete_nutrition": true,
  "required_nutrient_codes": [],
  "excluded_recipe_ids": [],
  "required_tags": [],
  "excluded_tags": [],
  "solver_time_limit_seconds": 3
}
```

Verify:

- Response `status` is `optimal`, `feasible`, or `infeasible`.
- Breakfast, lunch, and dinner are assigned for the default request when eligible candidates exist.
- `daily_totals.calories`, `protein`, `carbohydrates`, `fat`, and micronutrients equal the sum of selected meal nutrition.
- `deviations` reports +/- 5% tolerance status.
- `micronutrient_coverage` reports target, actual, coverage percent, and upper-limit metadata.
- No meal plan rows are created; this endpoint is preview-only.

Meal plan persistence requests:

```text
POST {{base_url}}/meal-plans
GET {{base_url}}/meal-plans/{{meal_plan_id}}
GET {{base_url}}/meal-plans
GET {{base_url}}/meal-plans?plan_date=2026-10-03
GET {{base_url}}/meal-plans?status=archived
DELETE {{base_url}}/meal-plans/{{meal_plan_id}}
```

Create plan body:

```json
{
  "plan_date": "2026-10-03",
  "meal_slots": [
    {
      "meal_type": "breakfast",
      "required": true
    },
    {
      "meal_type": "lunch",
      "required": true
    },
    {
      "meal_type": "dinner",
      "required": true
    },
    {
      "meal_type": "snack",
      "required": false
    }
  ],
  "max_total_time_minutes": 60,
  "require_complete_nutrition": true,
  "required_nutrient_codes": [],
  "excluded_recipe_ids": [],
  "required_tags": [],
  "excluded_tags": [],
  "solver_time_limit_seconds": 3
}
```

Verify:

- `POST {{base_url}}/meal-plans` returns `201 Created` with `meal_plan_id`, `plan_date`, `status`, `meals`, `daily_totals`, `targets`, `deviations`, and `micronutrient_coverage`.
- Repeating the same create request for the same user and date returns `409` with `PLAN_ALREADY_EXISTS`.
- `GET {{base_url}}/meal-plans/{{meal_plan_id}}` returns the same saved snapshot after recipe/profile edits.
- `GET {{base_url}}/meal-plans` lists generated plans by default.
- `DELETE {{base_url}}/meal-plans/{{meal_plan_id}}` returns `204 No Content` and changes the plan status to `archived`.

Meal swap request:

```text
POST {{base_url}}/meal-plans/{{meal_plan_id}}/items/{{meal_plan_item_id}}/swap
```

Headers:

```text
Authorization: Bearer {{access_token}}
Content-Type: application/json
```

Body:

```json
{
  "max_total_time_minutes": 20,
  "required_tags": ["quick"],
  "excluded_tags": [],
  "excluded_recipe_ids": []
}
```

Verify:

- Response is `200 OK` with the updated persisted plan.
- The selected meal's `recipe_id`, `recipe_name`, and nutrient snapshot change.
- Other meals remain unchanged.
- `daily_totals`, `deviations`, and `micronutrient_coverage` are recalculated from item snapshots.
- `targets` remain the original saved target snapshots.
- Reusing the same recipe is prevented.
- Impossible constraints return `422 NO_SWAP_CANDIDATE`.
- Swapping an archived plan returns `409 MEAL_PLAN_ARCHIVED`.

Unconstrained swap body:

```json
{}
```

Recipe create body:

```json
{
  "name": "Chicken Rice Bowl",
  "description": "Simple high-protein bowl.",
  "servings": 2,
  "prep_time_minutes": 5,
  "cook_time_minutes": 10,
  "difficulty": "easy",
  "ingredients": [
    {
      "food_id": "{{chicken_food_id}}",
      "quantity_grams": 100,
      "display_quantity": "100",
      "display_unit": "g",
      "position": 1
    },
    {
      "food_id": "{{rice_food_id}}",
      "quantity_grams": 100,
      "display_quantity": "100",
      "display_unit": "g",
      "position": 2
    }
  ],
  "steps": [
    {
      "position": 1,
      "instruction": "Warm the chicken.",
      "duration_seconds": 120,
      "timer": true
    },
    {
      "position": 2,
      "instruction": "Serve over rice.",
      "duration_seconds": 60
    }
  ],
  "tags": ["lunch", "quick", "high_protein"],
  "equipment": ["stovetop"]
}
```

Recipe update body to verify recalculation:

```json
{
  "ingredients": [
    {
      "food_id": "{{chicken_food_id}}",
      "quantity_grams": 200,
      "position": 1
    },
    {
      "food_id": "{{rice_food_id}}",
      "quantity_grams": 100,
      "position": 2
    }
  ]
}
```

Candidate preview request:

```json
{
  "meal_type": "lunch",
  "max_total_time_minutes": 20,
  "require_complete_nutrition": true,
  "required_nutrient_codes": ["calories", "protein"],
  "excluded_recipe_ids": [],
  "required_tags": ["quick"],
  "excluded_tags": []
}
```

Candidate preview expected shape:

```json
{
  "candidates": [
    {
      "recipe_id": "00000000-0000-0000-0000-000000000000",
      "name": "Chicken Rice Bowl",
      "servings": 2,
      "total_time_minutes": 15,
      "meal_tags": ["lunch"],
      "tags": ["high_protein", "lunch", "quick"],
      "required_equipment": ["stovetop"],
      "total_nutrition": [
        {
          "code": "calories",
          "name": "Calories",
          "amount": 295,
          "unit": "kcal",
          "complete": true,
          "missing_ingredient_count": 0
        }
      ],
      "per_serving_nutrition": [
        {
          "code": "calories",
          "name": "Calories",
          "amount": 147.5,
          "unit": "kcal",
          "complete": true,
          "missing_ingredient_count": 0
        }
      ],
      "nutrition_complete": true,
      "missing_nutrient_codes": [],
      "preference_match_count": 0,
      "matched_preference_food_names": [],
      "matched_preference_tags": []
    }
  ],
  "total_eligible": 1,
  "exclusion_summary": {
    "wrong_meal_type": 2
  },
  "excluded": [
    {
      "recipe_id": "00000000-0000-0000-0000-000000000001",
      "name": "Breakfast Oats",
      "reasons": ["wrong_meal_type"]
    }
  ],
  "allergy_filtering_supported": true,
  "unsupported_dietary_restrictions": [],
  "filter_order": [
    "active",
    "explicit_exclusions",
    "meal_type",
    "required_and_excluded_tags",
    "time",
    "equipment",
    "dietary_restrictions",
    "allergies",
    "disliked_foods",
    "nutrition_completeness"
  ]
}
```

Food list expected shape:

```json
{
  "items": [
    {
      "id": "00000000-0000-0000-0000-000000000000",
      "name": "Chicken Breast",
      "category": "protein",
      "source": "internal"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

USDA search expected shape:

```json
{
  "items": [
    {
      "fdc_id": 234567,
      "description": "Chicken breast, cooked",
      "data_type": "Foundation",
      "brand_owner": null
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 10
}
```

USDA import expected shape:

```json
{
  "status": "imported",
  "food": {
    "id": "00000000-0000-0000-0000-000000000000",
    "name": "Chicken Breast, Cooked",
    "source": "usda",
    "source_food_id": "234567",
    "category": "poultry_products",
    "description": "USDA FoodData Central import. Data type: Foundation.",
    "nutrients_per_100g": [
      {
        "code": "calories",
        "name": "Calories",
        "amount": 165,
        "unit": "kcal"
      }
    ],
    "servings": [
      {
        "name": "100 g",
        "grams": 100
      }
    ]
  }
}
```

Food detail expected shape:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "name": "Chicken Breast",
  "source": "internal",
  "source_food_id": "dev_chicken_breast",
  "category": "protein",
  "description": "Development fixture food. Approximate nutrition per 100g; not production USDA data.",
  "nutrients_per_100g": [
    {
      "code": "calories",
      "name": "Calories",
      "amount": 165,
      "unit": "kcal"
    }
  ],
  "servings": [
    {
      "name": "100 g",
      "grams": 100
    }
  ]
}
```

Profile requests:

```text
POST {{base_url}}/users/profile
GET {{base_url}}/users/profile
PATCH {{base_url}}/users/profile
```
