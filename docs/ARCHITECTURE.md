# Kcalm Backend Architecture

## Purpose

Kcalm is a backend-first nutrition planning system for mobile clients. The backend calculates nutrition targets, stores verified food and recipe data, assembles daily meal plans, validates nutrition totals, supports meal swaps, produces grocery lists, logs adherence, and uses AI only for language understanding and explanations.

The central rule is strict:

LLMs must never be used as the source of calories, macros, micronutrients, serving sizes, or target values. All nutrition numbers come from structured food data and deterministic backend code.

## Technology Stack

- Python 3.12+
- FastAPI
- PostgreSQL
- SQLAlchemy 2.x
- Alembic
- Pydantic v2
- pydantic-settings
- Google OR-Tools
- OpenAI Python SDK
- Pytest
- HTTPX
- Docker Compose

## Backend Layers

### Progress and Account Extensions

Weight, steps, daily metrics, habits, notifications, achievements, insights, account export/deletion, and
integration capability routes follow the existing router -> schema -> service -> model
boundary. `tracking_common.py` centralizes date validation and transactional commit/rollback.
Weight/steps/daily metrics use PostgreSQL upserts with user/date uniqueness. Habit completions and
notification events use deduplicated inserts. Read APIs never create progress data.

Achievements query owned persisted records; insights reuse existing intake aggregation
and actual snapshots. They do not call AI or estimate missing intake. Logging weight does
not automatically change saved profiles or plan targets. Password changes/resets increment
`users.token_version`, invalidating previously issued access and refresh tokens. Account
deletion relies on database cascades; export uses an explicit allowlist of owned tables
and snapshots and excludes credentials and shared catalog rows.

The integration registry reports implemented/configured capabilities without implying
external connectivity. New provider implementations must supply their actual clients,
authorization/credential lifecycle, and provider verification before becoming connected.

### API Layer

The nutrition/tracking batch adds owned water/fruit-veg/sleep records using the same
tracking transaction/date helpers and account export/deletion boundaries. Its only new
table is `daily_metrics`; clients cannot supply owner IDs or silently patch partial PUTs.

Actual intake adds nullable fiber and added sugar from existing nutrient snapshot rows.
Unknown nutrients propagate as null, including macro-only snacks and legacy snapshots.
Recipe definitions/fixtures explicitly include `added_sugar`; solver snapshots carry known
non-target nutrients without adding new objective terms or inventing targets. Imports
with missing data remain incomplete until the source data is reviewed and recalculated.

`app/nutrition/insights.py` is a pure deterministic scoring module. The insights service
assembles owned actual snapshots, saved-plan targets (preferred) or calculated profile
targets, and evidence of planned-meal logging and known calories and macros. Other unknown
nutrients do not gate these scores. Scores cannot certify unrecorded consumption and are
unavailable without enough evidence. Existing generic insight items remain unchanged.
See [Nutrition and Daily Tracking](NUTRITION_TRACKING.md) for formulas,
target precedence, score availability, API schemas, and limitations. No AI/provider calls
or score persistence are introduced.

The API layer is implemented with FastAPI routers. It owns HTTP concerns only:

- Request validation with Pydantic schemas.
- Authentication and authorization checks.
- Idempotency keys for plan generation, swaps, imports, and logs.
- Pagination, filtering, and response shaping.
- Mapping domain errors into HTTP responses.
- OpenAPI generation for Postman and mobile client integration.

The API layer must not contain nutrition formulas, solver logic, OpenAI prompt logic, or database-specific query orchestration beyond dependency injection.

### Service Layer

The service layer owns application workflows:

- User profile creation and updates.
- Nutrition target calculation and target revisions.
- Recipe and food candidate search.
- Meal plan generation orchestration.
- Meal swap orchestration.
- Grocery list generation.
- Meal logging and planned-vs-actual deviation calculation.
- AI request routing for natural-language parsing and explanations.

Services coordinate engines, repositories, and external integrations. Services return typed domain objects or Pydantic response models and keep transactions explicit.

### Database Layer

The database layer uses SQLAlchemy 2.x models, typed repositories, and Alembic migrations.

Responsibilities:

- Persist users, profiles, preferences, restrictions, equipment, targets, foods, nutrients, recipes, meal plans, logs, grocery lists, solver runs, and AI audit records.
- Enforce relational integrity with foreign keys and uniqueness constraints.
- Store source attribution for all nutrition data.
- Store versioned target snapshots so historical meal plans remain explainable.
- Use PostgreSQL numeric types for nutrition values where rounding matters.

Business rules should be validated in services and engines, while core integrity rules should also be enforced in the schema.

## Nutrition Engine

The nutrition engine is deterministic and test-heavy.

Responsibilities:

- Calculate BMR with the Mifflin-St Jeor equation.
- Calculate TDEE using activity multipliers.
- Derive calorie targets from goal and target rate.
- Derive macro targets by goal:
  - Protein anchored to body weight or lean mass where available.
  - Fat floor enforced before assigning carbohydrates.
  - Carbohydrates fill remaining calories.
- Load micronutrient targets from structured DRI/RDA reference tables.
- Calculate recipe nutrition from ingredient quantities, unit conversions, edible yield, and source food nutrient profiles.
- Calculate meal and day totals from selected recipes and portions.
- Validate plans against configured tolerances.

The nutrition engine must be pure where possible: the same inputs must produce the same outputs. It must not call OpenAI.

Recipe nutrition is calculated deterministically from local `FoodNutrient` rows and recipe ingredient grams:

`food_nutrient_per_100g * ingredient_quantity_grams / 100`

The current Recipe Database milestone persists recalculated recipe nutrient rows for future solver performance. These rows are generated by backend code during recipe create/update and are never accepted as client-provided nutrition facts. Missing food nutrient rows are surfaced with completeness metadata rather than fabricated.

## Optimization Engine

The optimization engine chooses meals from verified candidate recipes. It follows this flow:

User Profile -> Nutrition Targets -> Recipe Candidate Filtering -> Constraint Solver -> Nutrition Validation -> API Response

Responsibilities:

- Convert user targets, preferences, available time, equipment, restrictions, and logged deviations into a solver problem.
- Exclude impossible candidates before optimization.
- Use Google OR-Tools to choose recipes and portion choices.
- Enforce hard constraints such as allergies, dietary exclusions, equipment requirements, meal count, calorie bounds, macro bounds, and tracked micronutrient minimums.
- Optimize soft objectives such as preference match, variety, preparation time, cost when available, leftover reuse, and minimal deviation from targets.
- Produce explainable solver metadata for debugging and support.

The optimization engine must validate every result through the nutrition engine before returning it.

### Recipe Candidate Filtering

The current candidate filtering milestone prepares recipes for the future solver without invoking OR-Tools. `app/services/recipe_candidate_service.py` loads the authenticated user's saved profile, eager-loads recipe ingredients, tags, equipment, and persisted nutrition, then applies deterministic hard filters in a stable order.

Current hard filters:

- Active recipe only.
- Explicitly excluded recipe IDs.
- Meal type tags: `breakfast`, `lunch`, `pre_workout`, `dinner`, and `snack`.
- Required and excluded recipe tags.
- Total time, using request `max_total_time_minutes` first and profile `max_cooking_minutes` when the request omits an override.
- Required equipment subset of profile equipment.
- Supported dietary restrictions mapped to explicit tags.
- Conservative disliked-food exact matching against ingredient food names.
- Nutrition completeness from persisted `recipe_nutrients`.

The service returns candidates in deterministic name/id order, with no duplicate candidates. Rejected recipes include structured reason codes and the response includes first-reason exclusion summary counts.

Soft preferences are metadata only in this milestone. Preferred food matches are exposed so a future solver can rank or score them, but filtering does not rank, optimize, or exclude based on preferences.

Allergy filtering now uses reviewed per-food `allergen_codes` and `allergen_reference`.
Missing reviews or unsupported profile allergy names exclude candidates; known conflicts
also exclude them. Pescatarian and halal require explicit recipe tags. This same filtering
applies to daily/weekly/adaptive plans and swaps. Cross-contact/medical safety remains
unassessed, and natural-language AI safety claims remain unsupported. See the
[Frontend API Guide](FRONTEND_API_GUIDE.md) for exact scope and operator review procedure.

### Daily Solver Preview

The current OR-Tools milestone adds a non-persisted one-day solver preview. The endpoint orchestration lives in `app/services/meal_solver_service.py`, while the OR-Tools CP-SAT model is isolated in `app/meal_planning/solver.py`. Integer scaling helpers live in `app/meal_planning/scaling.py`.

Solver flow:

```text
Authenticated User
    -> saved profile
    -> deterministic calorie, macro, and micronutrient targets
    -> recipe candidate filtering
    -> eligible candidate DTOs
    -> OR-Tools CP-SAT
    -> structured preview response
```

The solver does not query arbitrary recipes, recalculate recipe nutrition from text, call USDA, call OpenAI, or persist plans. It receives only candidate DTOs already accepted by candidate filtering.

Meal-slot rules:

- Breakfast, lunch, and dinner are required by default.
- Snack is optional by default.
- A request may override slots for preview/testing.
- Meal types are matched from recipe tags, not recipe names.
- The same recipe cannot fill multiple slots in one day.

Portion strategy:

- The MVP solver uses `1.0` recipe serving per selected meal.
- Discrete multipliers such as `0.5`, `1.5`, and `2.0` are deferred.
- Arbitrary floating portions are avoided to keep CP-SAT deterministic and explainable.

Nutrition optimization:

- Recipe candidate per-serving nutrition is the source of solver values.
- OR-Tools receives integer-scaled values using thousandths of each native unit.
- Calories and macros use a preferred +/- 5% tolerance for reporting.
- Nutrition tolerance is optimized through penalties, not hard feasibility bands, so the closest valid structural plan can still be returned.
- Micronutrients add shortfall penalties.
- Upper-limit excess penalties apply only where the current target metadata represents applicable `UL` or `CDRR` semantics.
- Solver statuses are mapped to `optimal`, `feasible`, and `infeasible`.
- The default timeout is 3 seconds, with one search worker and fixed seed for stable results.

### Daily Meal Plan Persistence

Daily meal plan persistence stores one-day solver results and provides the reusable persistence boundary for daily plans, weekly orchestration, grocery list generation, swaps, actual-intake logging, and adaptive next-day generation. It does not itself implement full-day regeneration, compensation policy, or AI explanation generation.

Persistence flow:

```text
Authenticated User
    -> saved profile
    -> deterministic targets
    -> candidate filtering
    -> OR-Tools solver
    -> feasible or optimal solver result
    -> meal-plan snapshot transaction
```

`POST /api/v1/meal-plans` calls the existing solver-preview service and persists only `optimal` or `feasible` results. `infeasible` results return a controlled `MEAL_PLAN_INFEASIBLE` error and do not create any meal-plan rows.

The persistence boundary lives in `app/services/meal_plan_service.py`. It owns duplicate-date checks, transaction management, snapshot writes, ownership-aware reads, list filtering, and soft archive. It does not rebuild solver constraints or recalculate recipe nutrition.

Current persisted plan tables:

- `meal_plans`
- `meal_plan_items`
- `meal_plan_item_nutrients`
- `meal_plan_item_ingredients`
- `meal_plan_micronutrient_targets`

Historical stability is handled through snapshots stored with the plan:

- Recipe name snapshot.
- Meal type and selected serving amount.
- Item nutrient contribution snapshots.
- Item ingredient quantity snapshots for grocery preview.
- Calorie, protein, carbohydrate, and fat target snapshots.
- Micronutrient target, minimum, upper limit, upper-limit type, unit, and name snapshots.
- Solver status, objective value, solve time, candidate count, and tolerance flag.

Read APIs reconstruct daily totals, macro deviations, and micronutrient coverage from these persisted snapshots. They do not look back at mutable recipe nutrients or the user's current profile for saved-plan nutrition.

One active `generated` plan is allowed per user per `plan_date`. A partial unique PostgreSQL index enforces this while allowing archived historical plans for the same date. `DELETE /api/v1/meal-plans/{meal_plan_id}` performs a soft archive by setting status to `archived`.

### Meal Swap

The current swap service supports replacing one item inside an existing generated daily plan. It does not implement swap option lists, full-day regeneration, or automatic next-day compensation. Natural-language swap parsing lives in the AI constraint layer and delegates back to this service after validation.

Swap flow:

```text
Persisted Plan
    -> target item lookup
    -> locked meal snapshots
    -> candidate filtering for the target meal type
    -> excluded current and locked recipe IDs
    -> existing OR-Tools solver
    -> transactional item snapshot update
    -> updated persisted plan response
```

The service boundary lives in `app/services/meal_swap_service.py`. It owns ownership/status validation, item lookup, locked nutrition extraction, candidate filtering orchestration, solver invocation, and transactional snapshot replacement. Routes only handle HTTP validation and response shaping.

Locked meals:

- Every item except the selected item is locked by default.
- Locked recipe IDs are excluded from replacement candidates to prevent duplicate reuse.
- Locked nutrition is read from `meal_plan_item_nutrients`.
- Locked item snapshots are not modified.

Target behavior:

- Swaps use the meal plan's saved macro and micronutrient target snapshots.
- Swaps do not recalculate targets from the user's current profile.
- If a profile changes after plan creation, old plan swaps still optimize against the old saved target snapshot.

Solver reuse:

- The OR-Tools solver accepts optional locked nutrition as base daily totals.
- The same calorie, macro, micronutrient shortfall, upper-limit, tolerance, and deterministic tie-breaking objective is used.
- Candidate recipes still come from `app/services/recipe_candidate_service.py`; swaps do not query recipes directly.

Unsupported swap constraints:

- `different_protein` is deferred until recipes have reliable structured protein-source metadata.
- `eating_out` is deferred until restaurant or external meal records exist.
- Free-form natural-language swap parsing is handled only by the guarded AI constraint layer, then passed back into this existing swap service.

Failed swaps return controlled errors and leave the persisted plan unchanged.

### Weekly Plan Generation / Grocery Foundation

Weekly planning is an orchestration layer over the existing daily candidate filtering, OR-Tools solver, and daily persistence flow. It does not introduce a separate weekly optimizer.

Weekly flow:

```text
Authenticated User + requested start_date
    -> saved profile and daily targets
    -> seven daily plan requests
    -> existing candidate filtering
    -> existing daily OR-Tools solver
    -> persisted daily meal plans
    -> WeeklyMealPlan container
    -> item ingredient snapshots
    -> grocery preview aggregation
```

Model strategy:

- `weekly_meal_plans` stores the owner, `start_date`, derived `end_date`, status, and timestamps.
- `meal_plans.weekly_plan_id` links generated daily plans to the week.
- Daily meal items are not duplicated at the weekly level.
- `meal_plan_item_ingredients` stores grocery-relevant ingredient snapshots per selected meal item.

Week semantics:

- MVP weeks are seven consecutive calendar dates.
- Any `start_date` is allowed because the PRD does not require Monday-Sunday semantics.
- `end_date` is derived as `start_date + 6 days`.

Transaction strategy:

- Weekly creation is fully atomic.
- If any day fails, the week and all newly generated member daily plans are rolled back.
- Existing active generated daily plans inside the requested range are treated as conflicts and are not overwritten.

Variety behavior:

- The orchestrator tries to exclude the previous day's selected recipe IDs when generating the next day.
- This avoids adjacent-day exact recipe repetition when alternatives exist.
- If that variety constraint makes a day infeasible, the day is retried without the variety exclusion so a sparse recipe catalog can still produce a week.

Grocery preview strategy:

- Grocery aggregation reads `meal_plan_item_ingredients`, not live `recipe_ingredients`.
- Snapshot quantity is `recipe_ingredient.quantity_grams * meal_plan_item.servings`.
- Aggregation identity is stable `food_id`.
- Output includes food name, total grams, and useful Food metadata such as source/source food ID/category.
- Plans missing ingredient snapshots return `GROCERY_SNAPSHOT_MISSING` instead of silently falling back to mutable recipe data.

### Smart Grocery List

Smart grocery lists persist the weekly grocery aggregation into user-manageable rows while keeping weekly plans and recipes immutable from grocery edits.

Flow:

```text
WeeklyMealPlan
    -> persisted MealPlanItemIngredientSnapshot rows
    -> grocery aggregation by Food ID
    -> GroceryList
    -> GroceryListItem rows
```

Layer responsibilities:

- API layer: `POST /api/v1/weekly-meal-plans/{weekly_plan_id}/grocery-list` creates a list, and `/api/v1/grocery-lists` handles list retrieval, item edits, regeneration, manual items, and archive.
- Service layer: `app/services/grocery_service.py` owns aggregation reuse, ownership checks, duplicate active-list checks, deterministic category mapping, and transaction boundaries.
- Database layer: `grocery_lists` stores user/week/status metadata and `grocery_list_items` stores generated or manual rows with checked state.
- Nutrition/data rule: automatic grocery rows are generated from persisted ingredient snapshots only; live recipe ingredients, USDA, and OpenAI are not consulted.

Generation behavior:

- A weekly plan can have only one active grocery list; duplicates return `GROCERY_LIST_ALREADY_EXISTS`.
- Automatic list items merge repeated ingredients by `food_id`.
- Different foods with the same display name remain separate because display names are snapshots, not aggregation keys.
- Generated quantities use grams as the canonical unit and store `quantity_grams`.
- `food_name_snapshot` keeps existing lists stable if recipe ingredients or food names later change.

Editable behavior:

- Users may check/uncheck items and edit item quantity, unit, or deterministic grocery category.
- Manual items use `food_id = null`, `manually_added = true`, and the user-supplied unit.
- Removing an item permanently deletes that row from the grocery list.
- Regeneration deletes and recreates automatic items from persisted weekly snapshots, preserves manual items, preserves automatic checked state by Food ID, and resets generated quantities to snapshot totals.
- Archive is soft; archived lists are hidden from default listing and cannot be modified.

Category strategy:

- Existing Food categories map deterministically to grocery categories: produce, meat_seafood, dairy, grains, pantry, frozen, or other.
- Unknown categories fall back to `other`.
- Store-specific aisle ordering, retailer integrations, and household unit conversion are deferred.

Archive behavior:

- Weekly archive is soft.
- Generated member daily plans are archived with the week.
- Unrelated standalone daily plans are not modified.

### Adaptive Logging / Ate-as-Planned Tracking

Meal logging adds an actual-intake layer beside immutable planned meal snapshots.

Flow:

```text
Persisted MealPlan
    -> planned MealPlanItemNutrientSnapshot rows
    -> MealLog
    -> MealLogNutrientSnapshot rows
    -> planned-vs-actual summary
```

Layer responsibilities:

- API layer: nested meal-plan routes accept structured log requests and return actual summaries.
- Service layer: `app/services/meal_log_service.py` owns ownership checks, archived-plan rejection, idempotent log replacement, deterministic actual nutrition calculations, and transaction boundaries.
- Database layer: `meal_logs` stores one active/current log per meal-plan item and `meal_log_nutrients` stores historical actual nutrient snapshots.
- Nutrition rule: logging reads only structured persisted data; it never calls OpenAI, USDA, text descriptions, or live recipe ingredients for ate-as-planned logs.

Log types:

- `ate_as_planned` copies the planned `meal_plan_item_nutrients` rows exactly.
- `corrected` with `source_type = food` calculates from local `food_nutrients.amount` per 100g and `quantity_grams`.
- `corrected` with `source_type = recipe` calculates from `recipe_nutrients.per_serving_amount` and `servings`.

Planned vs actual separation:

- Planned meal item nutrients, target snapshots, recipe IDs, and plan totals are not overwritten by logs.
- Actual consumed nutrients are stored separately under the log.
- If a food or recipe changes after logging, existing actual snapshots stay unchanged.

Current-log behavior:

- The MVP keeps one active log per meal-plan item.
- Re-logging updates the same active log row and replaces actual nutrient snapshots transactionally.
- Reset deletes the active log row.
- Full revision history is deferred.

Summary behavior:

- Actual totals sum active `meal_log_nutrients`.
- Unlogged meal-plan items do not count as consumed.
- Summary output includes planned totals, actual totals, target snapshots, actual-vs-planned differences, actual-vs-target differences, and missing actual target nutrient metadata.
- Adherence is deterministic: `ate_as_planned_count / planned_meals_count * 100`.

Limitations:

- Archived plans cannot be logged.
- Missing structured nutrients are not invented.
- Full-day regeneration, automatic target recalibration, free-text logging, barcode/photo logging, restaurant matching, and wearable sync are deferred.

### Adaptive Next-Day Compensation

Adaptive next-day planning is a service-layer workflow in `app/services/adaptive_planning_service.py`. It uses actual intake snapshots from the logging layer, source-day target snapshots from persisted meal plans, and the existing candidate filtering plus OR-Tools daily solver. It does not create a second solver and does not mutate historical plans or logs.

Flow:

```text
Previous Day Persisted Plan
    -> Actual Intake Logs
    -> Daily Deviation
    -> Safe Compensation Policy
    -> Adjusted Next-Day Target Input
    -> Existing Candidate Filtering
    -> Existing OR-Tools Solver
    -> Persisted Next-Day Plan
```

Layer responsibilities:

- API layer: `POST /api/v1/meal-plans/{source_plan_id}/adaptive-preview` and `POST /api/v1/meal-plans/{source_plan_id}/generate-next-day` handle auth, request validation, and response shaping.
- Adaptation service: validates source plan ownership/status, requires complete logging, calculates actual-minus-target deviations, applies policy caps, builds adjusted solver targets, and coordinates preview or persistence.
- Logging service: remains the source of actual intake totals; unlogged meals are not inferred as eaten.
- Meal-plan service: persists the generated next-day plan with immutable target and item snapshots.
- Database layer: `meal_plan_adaptations` stores traceability metadata for generated adaptive plans.

Deviation rules:

- Deviations are calculated from actual log totals minus the source plan's saved target snapshots.
- Yesterday's targets are never recomputed from the current profile.
- Calories, protein, carbohydrates, and fat are required for compensation.
- Micronutrient deviations are reported from available log snapshots, but they do not change next-day hard targets in the MVP.

Compensation policy:

- Current `policy_version` is `adaptive_v1`.
- `compensation_fraction` is `0.25`.
- Calorie adjustment is capped to the smaller of `250 kcal` or `10%` of the source calorie target.
- Adjusted calories cannot drop below `1200 kcal`.
- Overage lowers the next-day target conservatively; under-eating raises it conservatively.
- Protein and fat targets remain anchored to the source plan. Carbohydrates fill remaining adjusted calories through the existing macro helper.

Persistence and transaction behavior:

- Preview does not write a new meal plan or adaptation snapshot.
- Generation uses `source_plan.plan_date + 1 day` and returns `PLAN_ALREADY_EXISTS` if a generated plan already exists for that date.
- The generated plan and its adaptation metadata are committed atomically.
- Source plan rows and source log rows remain unchanged.

### Recipe Execution / Recipe Player Foundation

Recipe execution provides backend state and immutable cooking-step data for a future mobile recipe player. It is intentionally separate from recipe CRUD, meal-plan generation, swaps, grocery, meal logs, and AI.

Flow:

```text
Recipe or MealPlanItem
    -> execution session start
    -> immutable recipe/serving/equipment/ingredient/step snapshots
    -> current step progress and timer metadata
    -> completed or abandoned history
```

Layer responsibilities:

- API layer: `app/api/routes/recipe_execution.py` handles auth, request validation, response shaping, and non-leaking ownership behavior.
- Service layer: `app/services/recipe_execution_service.py` owns direct recipe starts, meal-plan-item starts, duplicate active-session checks, snapshot creation, progress transitions, completion, abandonment, and rollback boundaries.
- Database layer: `recipe_execution_sessions` stores user/session state and session-level snapshots, while `recipe_execution_step_snapshots` stores ordered immutable step snapshots.
- Recipe layer: `recipe_steps` owns structured authoring metadata such as phase, duration, explicit timer fields, cue/action keys, and nullable media placeholders.

Snapshot strategy:

- Direct recipe starts require an active recipe and positive servings.
- Meal-plan-item starts verify ownership and use the persisted item recipe name, serving amount, and ingredient snapshots.
- Recipe name, equipment summary, ingredient summary, ordered instructions, phase, duration, timer metadata, and media placeholders are copied at session start.
- Already-started sessions do not change if a recipe is renamed, archived, or edited later.
- Only one active `not_started` or `in_progress` session is allowed per meal-plan item; completed and abandoned sessions remain historical.

Timer strategy:

- `duration_seconds` is an estimated step duration.
- `timer_required` and `timer_seconds` are explicit timer metadata.
- The backend does not infer timers from vague text, call OpenAI for timers, or run countdown workers.
- Mobile clients render countdown state from persisted metadata.

Limitations:

- Step-level ingredient and equipment mapping is not modeled yet; execution responses expose recipe/session-level summaries and empty per-step arrays.
- Meal plans do not snapshot recipe steps before execution, so starting from a meal-plan item reads current recipe steps and snapshots them at execution start.
- Completing execution does not log the meal as eaten.
- Animation rendering, video/image generation, voice, camera recognition, smart appliance control, delivery, restaurant matching, and wearable integration are outside the backend milestone.

## AI Layer

OpenAI may be used for:

- Parsing natural-language meal requests into structured constraints.
- Extracting user preferences from text.
- Extracting exclusions or allergies from text for user confirmation.
- Producing plain-language explanations from already-calculated targets, plans, and solver metadata.
- Turning structured recipe steps into concise user-facing cooking guidance, without changing ingredients or nutrition numbers.

OpenAI is prohibited from:

- Inventing calories, macros, micronutrients, serving sizes, or RDAs.
- Generating final meal plans without solver validation.
- Creating unverified recipes as nutrition-bearing entities.
- Modifying target values.
- Deciding whether a plan is nutritionally valid.

AI outputs that affect constraints must be treated as proposals and normalized into typed backend structures before use.

### Natural-Language Constraint Layer

The implemented AI constraint layer is stateless and lives behind a strict boundary:

- SDK integration: `app/integrations/openai_client.py`.
- Service validation and normalization: `app/services/ai_constraint_service.py`.
- Schemas: `app/schemas/ai.py`.
- API routes: `POST /api/v1/ai/constraints/interpret`, `POST /api/v1/ai/meal-options`, and `POST /api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/ai-swap`.

Flow:

```text
Natural language
    -> OpenAI structured interpretation
    -> Pydantic validation
    -> canonical tag and food-name validation
    -> existing recipe candidate filtering
    -> existing OR-Tools swap service when mutating a meal
```

Guardrails:

- OpenAI returns only `NaturalLanguageMealConstraintLLMOutput`.
- Unknown fields, IDs, nutrition numbers, and unsupported tags are rejected before downstream use.
- Food avoidance phrases are resolved against local `foods` rows. The LLM never supplies `food_id` or `recipe_id`.
- Allergy-like and unsupported medical/restaurant/different-protein intents remain `unsupported_constraints`.
- Ambiguous requests return structured clarification instead of guessing.
- AI swap refuses to mutate a plan when clarification or unsupported constraints are present.
- AI meal options calls candidate filtering only; it does not invoke OR-Tools.
- AI swap calls the existing swap service, so locked meals, current recipe exclusion, target snapshots, candidate filtering, OR-Tools, and transaction rollback remain authoritative.

## Integrations

### USDA FoodData Central

USDA FoodData Central is the planned base data source for verified food and nutrient data. Imports must preserve:

- External food identifiers.
- Data type and source.
- Nutrient identifiers.
- Per-100g nutrient values.
- Publication or import version.

### Supplemental Branded Food Database

A licensed branded-food source may be added for packaged items. It must use the same source attribution and verification model as USDA imports.

### OpenAI

OpenAI is called only through the AI integration/service. Prompts are tightly scoped and structured outputs are validated with Pydantic before downstream use. The current milestone logs privacy-safe operation/model/latency/success/failure metadata, but does not persist prompt/response audit records yet.

### Mobile Clients

The backend exposes REST APIs for iOS and Android. Client-specific animation rendering is out of backend scope, but the backend provides structured recipe steps, timers, and animation component keys.

### Postman

The MVP backend is Postman-ready through FastAPI's OpenAPI document and documented manual flows:

- Swagger UI at `/docs`.
- OpenAPI JSON at `/openapi.json`.
- Local environment base URL: `http://127.0.0.1:8000/api/v1`.
- Idempotent development seed commands for foods and recipes.
- Manual checklist coverage for auth, profile, targets, foods, recipes, candidate preview, daily plan, swap, weekly plan, grocery list, logging, adaptive planning, AI constraints, and recipe execution.

Generated Postman collections and staging/production environment templates remain deferred.

## Final MVP Hardening Notes

The final backend hardening pass added an end-to-end MVP integration test covering the full user journey from registration through recipe execution completion. The test uses mocked USDA/OpenAI integrations and structured seed data, so the automated suite never depends on live external services.

Audit outcomes:

- The service boundary remains backend-first: routers validate/authenticate and services own workflow logic.
- Nutrition source-of-truth remains `FoodNutrient -> recipe calculation -> recipe nutrient snapshot -> solver candidate -> meal-plan snapshot -> intake snapshot`.
- Historical snapshots are covered by existing tests for recipe edits after plan creation, grocery list stability after recipe edits, food edits after logging, profile changes after plan generation, and recipe edits after execution start.
- User-owned resources use authenticated access and non-leaking ownership behavior where applicable.
- Multi-row writes for recipe creation/update, plan generation, swaps, weekly generation, grocery generation/regeneration, meal logging, adaptive generation, and execution session creation are transactional.
- OpenAI remains isolated to structured language interpretation; allergy/safety and medical constraints are conservative unsupported metadata, not false safety claims.

## P0 Daily Slots and Reviewed Development Catalog

`pre_workout` is a first-class recipe tag and validated API/persisted meal type; `snack`
is separate. The existing generic solver slot assignment, snapshot persistence, weekly
flows, and swap orchestration use explicit slot requests without a new solver or service.
Legacy omitted-slot defaults remain breakfast/lunch/dinner plus optional snack.

The repeatable development seed now has 12 modeled foods and ten recipes for each of
the four frontend slots (plus the original snack). Recipe nutrition is still calculated
only from structured food rows. Explicit per-fixture ingredient specifications and
allergen lists live in `app/seed_data/allergen_reviews.py`, applied through the shared
review validator within seed transactions. Production imports are not automatically
reviewed. Candidate filtering remains fail-closed and never promises cross-contact safety.
See [P0 Catalog](P0_CATALOG.md) for counts, source scope, and dietary limitations.

The active-plan-log and standalone-snack GET handlers reuse existing response models
and ownership boundaries. An optional `MealSwapRequest.recipe_id` narrows already
filtered candidates before the existing solver; it cannot bypass profile constraints,
allergen reviews, locked recipes, or nutrition validation.

## Testing Strategy

### Unit Tests

- Nutrition formulas and macro allocation.
- Unit conversion and ingredient scaling.
- Recipe nutrition rollups.
- Constraint extraction schema validation.
- Candidate filtering.
- Solver input construction.
- Plan validation rules.

### Integration Tests

- API routes with FastAPI and HTTPX.
- PostgreSQL-backed repositories.
- Alembic migration upgrade/downgrade where practical.
- USDA import pipeline with small fixtures.
- Meal generation and swap workflows with deterministic seed data.

### Solver Tests

- Feasible day plan.
- Infeasible restrictions.
- Tight macro targets.
- Micronutrient minimum enforcement.
- Meal swap without breaking day totals.
- Regression fixtures for known plans.

### AI Tests

- Mocked OpenAI responses.
- Pydantic validation of structured outputs.
- Guardrail tests proving nutrition numbers from AI are ignored or rejected.
- Prompt version snapshot tests for high-risk workflows.

### Contract and Postman Tests

- OpenAPI schema validation.
- Postman collection smoke tests against local Docker Compose.
- Example requests for onboarding, target calculation, plan generation, swap, logging, and grocery list generation.
