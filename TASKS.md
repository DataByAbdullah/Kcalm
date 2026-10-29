# Kcalm Backend Tasks

## Priority 2 and 3 Extensions

- [x] Dated weight upsert/history/delete with target-weight progress.
- [x] Manual dated steps, history, correction, and deletion.
- [x] Daily habits, edit/delete, per-date completion and history.
- [x] Derive achievements from actual owned progress, intake, and execution records.
- [x] Derive deterministic insights using real intake/progress; distinguish missing data.
- [x] Persist notification inbox with idempotent achievement sync and read state.
- [x] Authenticated password change with current-password verification and token revocation.
- [x] Delete account through database cascades; preserve shared catalog and other users.
- [x] Versioned JSON export of owned records/snapshots without credentials.
- [x] Pescatarian/halal tags and reviewed-allergen candidate filtering shared by plan flows.
- [x] Grocery detail completion counts while preserving existing editing.
- [x] Integration capability registry with honest configuration/unimplemented status.
- [x] Six focused additive migrations without unrelated index/constraint churn.
- [x] Targeted tests for each extension and transactional rollback.
- [x] Frontend/Postman integration guide with exact payloads and limitations.
- [ ] Review production catalog allergens/diet certifications with source attribution.
- [ ] Choose and implement wearable, push, and grocery-delivery providers with credentials.

## Project Foundation

- [x] Create Python 3.12 FastAPI project structure.
- [x] Configure pydantic-settings for local, test, staging, and production settings.
- [x] Configure Docker Compose with PostgreSQL service.
- [x] Add SQLAlchemy 2.x async or sync database setup.
- [x] Add Alembic migration setup.
- [ ] Add pytest, HTTPX, coverage, linting, and formatting tooling.
- [x] Add OpenAPI metadata and API version prefix.
- [x] Add health check endpoint.

## Database and Migrations

- [x] Create identity and auth tables.
- [x] Create user profile and preference capture tables.
- [ ] Create profile, activity level, restrictions, equipment, and preference tables.
- [ ] Create nutrient and nutrient reference value tables.
- [x] Create food, food nutrient, and food serving tables.
- [ ] Create food source, import batch, unit, and conversion tables.
- [x] Create recipe, ingredient, step, tag, equipment, and calculated nutrition tables.
- [ ] Create nutrition target set and micronutrient target tables.
- [x] Create daily meal plan, meal plan item, item nutrient snapshot, and micronutrient target snapshot tables.
- [x] Create weekly meal plan and meal item ingredient snapshot tables.
- [ ] Create materialized meal plan nutrition total, solver run, and swap tables.
- [x] Create meal log and actual nutrient snapshot tables.
- [x] Create adaptive next-day meal plan metadata table.
- [x] Create recipe execution session and step snapshot tables.
- [ ] Create materialized daily nutrition log tables.
- [x] Create grocery list and grocery list item tables.
- [ ] Create AI interaction audit table.
- [ ] Add indexes for food search, recipe filtering, plan lookup, and log lookup.
- [x] Add development recipe seed data for tests and Postman examples.

## Nutrition Data

- [x] Define MVP food nutrient codes and units for internal seed data.
- [x] Define USDA FoodData Central import mapping.
- [x] Build USDA import service with source attribution.
- [x] Build deterministic unit conversion service.
- [ ] Add validation for missing or inconsistent food nutrient records.
- [x] Add development food fixtures used in tests and Postman examples.
- [ ] Evaluate supplemental branded-food database integration.

## Nutrition Engine

- [x] Implement Mifflin-St Jeor BMR calculation.
- [x] Implement TDEE calculation from activity multipliers.
- [x] Implement calorie target derivation by goal and target rate.
- [x] Implement macro split logic by goal.
- [x] Implement micronutrient target lookup from DRI/RDA tables.
- [x] Implement recipe nutrition rollup from ingredients.
- [x] Implement saved daily plan nutrition total reconstruction from meal item snapshots.
- [ ] Implement broader meal, day, and plan nutrition total calculation services.
- [ ] Implement plan validation against calorie, macro, and micronutrient targets.
- [ ] Add unit tests for all nutrition formulas and rollups.

## API Milestones

- [x] Implement auth endpoints.
- [x] Implement current user endpoint.
- [x] Implement profile CRUD endpoints.
- [x] Implement BMR/TDEE calculation endpoint.
- [x] Extend nutrition calculation endpoint with calorie and macro targets.
- [x] Implement micronutrient target endpoint.
- [x] Implement food search and food detail endpoints.
- [x] Implement USDA food search and single-food import endpoints.
- [ ] Implement restriction, preference, and equipment endpoints.
- [ ] Implement target calculation endpoint.
- [ ] Implement target confirmation and history endpoints.
- [ ] Implement admin food import endpoints.
- [x] Implement recipe search and detail endpoints.
- [x] Implement authenticated recipe create, update, and archive endpoints.
- [x] Implement authenticated recipe candidate preview endpoint.
- [ ] Implement admin recipe creation and validation endpoints.
- [x] Implement non-persisted daily solver preview endpoint.
- [x] Implement daily meal plan generation endpoint.
- [x] Implement daily meal plan list, detail, and soft archive endpoints.
- [ ] Implement meal plan confirm and full-day regenerate endpoints.
- [x] Implement adaptive next-day preview and generation endpoints.
- [x] Implement weekly meal plan endpoints.
- [x] Implement single-meal apply-swap endpoint.
- [ ] Implement swap option endpoint.
- [x] Implement meal logging endpoints.
- [x] Implement adaptation preview endpoint.
- [x] Implement grocery list generation and item management endpoints.
- [x] Implement recipe execution session, progress, complete, and abandon endpoints.
- [ ] Implement solver diagnostics endpoints.

## Meal Optimization

- [x] Define recipe candidate filter input and output schemas.
- [x] Implement recipe candidate filtering.
- [x] Define daily solver input and output schemas.
- [x] Implement MVP fixed 1.0-serving solver portion strategy.
- [ ] Implement portion option generation.
- [x] Implement OR-Tools CP-SAT daily plan solver.
- [x] Implement locked-meal nutrition support for single-meal swaps.
- [x] Implement hard constraints for candidate eligibility, meal slots, recipe reuse, and fixed portion bounds.
- [x] Implement nutrition deviation objective for calories, macros, and micronutrient shortfall.
- [x] Persist one-day solver results with immutable recipe, nutrient, and target snapshots.
- [ ] Implement soft objective scoring for preferences, variety, time, repetition, and ingredient reuse.
- [x] Implement infeasibility reporting.
- [ ] Implement post-solver nutrition validation.
- [x] Implement meal swap solver flow.
- [ ] Add solver regression fixtures.

## AI Features

- [x] Create AI service boundary using OpenAI Python SDK.
- [x] Define prompt versioning and structured output schemas.
- [x] Implement natural-language meal request parsing.
- [x] Implement preference extraction for request-scoped soft food preferences.
- [x] Implement swap request parsing.
- [ ] Implement target explanation from calculated data.
- [ ] Implement meal plan explanation from validated data.
- [ ] Implement swap explanation from validated data.
- [x] Add guardrails rejecting AI-provided nutrition numbers and arbitrary IDs.
- [ ] Add AI interaction audit logging.
- [x] Add mocked AI tests.

## Grocery Lists

- [x] Generate weekly grocery preview from persisted meal plan ingredient snapshots.
- [x] Merge duplicate ingredients across recipes for weekly grocery preview.
- [x] Generate persisted grocery list from finalized weekly meal plan snapshots.
- [x] Map grocery items to deterministic categories where supported.
- [ ] Group grocery items by store-specific aisle.
- [x] Support manual add, remove, generated quantity edit, and checked state.
- [x] Add tests for quantity merging and no duplicate/missing ingredients.

## Adaptive Logging

- [x] Implement ate-as-planned logging.
- [x] Implement structured food and recipe correction logging.
- [ ] Implement swapped or skipped meal logging.
- [x] Calculate actual daily nutrition totals from active logs.
- [x] Expose planned-vs-actual summary and adherence metadata.
- [x] Support reset/unlog for current active item log.
- [x] Implement deterministic next-plan compensation.
- [x] Add tests for logged deviations and planned-vs-actual summaries.
- [x] Add tests for next-plan adjustments.

## Recipe Execution

- [x] Add recipe step phase, explicit timer duration, and media placeholder metadata.
- [x] Persist recipe execution sessions with immutable recipe/serving/equipment/ingredient snapshots.
- [x] Persist ordered recipe execution step snapshots.
- [x] Start execution directly from an active recipe.
- [x] Start execution from an owned persisted meal-plan item.
- [x] Prevent duplicate active execution sessions for one meal-plan item.
- [x] Resume in-progress execution sessions through session detail.
- [x] Progress current step, complete individual steps, complete sessions, and abandon sessions.
- [x] Enforce execution session ownership.
- [x] Preserve execution snapshots after recipe edits.
- [ ] Add step-level ingredient and equipment reference mapping.
- [ ] Add client-facing timer start/complete endpoints if product needs persisted timer state.
- [ ] Add voice, camera, smart-appliance, or animation-rendering integrations.

## Testing

- [ ] Add database repository tests.
- [ ] Add Alembic migration tests.
- [x] Add API integration tests with HTTPX.
- [x] Add BMR/TDEE nutrition engine unit and API tests.
- [x] Add calorie and macro target unit and API tests.
- [x] Add micronutrient target unit and API tests.
- [x] Add food database model, seed, and API tests.
- [x] Add mocked USDA search, fetch, mapping, import, duplicate, and auth tests.
- [x] Add recipe database, nutrition rollup, seed, and API tests.
- [x] Add recipe candidate filtering and preview API tests.
- [x] Add OR-Tools daily solver unit and preview API tests.
- [x] Add daily meal plan persistence API, snapshot, ownership, duplicate, infeasible, archive, and rollback tests.
- [x] Add single-meal swap API, locked snapshot, target preservation, filter, ownership, archived-plan, and deterministic solver tests.
- [ ] Add broader nutrition engine unit tests.
- [x] Add solver unit and integration tests.
- [x] Add AI guardrail tests.
- [x] Add weekly meal plan and grocery preview tests.
- [x] Add final grocery list workflow tests.
- [x] Add meal logging tests.
- [x] Add end-to-end tests for onboarding target calculation, plan generation, swap, logging, and grocery list generation.
- [x] Add recipe execution snapshot, progress, ownership, and history tests.
- [ ] Add test coverage reporting.

## Postman Support

- [ ] Generate Postman collection from OpenAPI.
- [ ] Create local Docker Compose Postman environment.
- [ ] Create staging Postman environment template.
- [ ] Add seeded example user and data setup flow.
- [x] Add request examples for all MVP backend endpoints.
- [x] Add Postman smoke test workflow.

## Documentation

- [x] Keep architecture docs aligned with implementation.
- [x] Document environment variables.
- [x] Document local setup.
- [ ] Document data import procedure.
- [x] Document solver tuning policy.
- [x] Document AI guardrails and prompt versioning.
- [x] Document Postman usage.

## Final Backend Hardening

- [x] Audit full backend architecture boundaries.
- [x] Remove committed secret-like value from `.env.example`.
- [x] Harden recipe execution timer-required behavior when `timer_seconds` is present.
- [x] Add full backend MVP end-to-end integration test.
- [x] Run Alembic current/head/upgrade checks.
- [x] Run fresh-database migration smoke test.
- [x] Run full `pytest -q` suite.
- [x] Run `python -m compileall app`.
- [x] Run FastAPI startup smoke with health/docs/OpenAPI checks.

## Frontend P0 Only

- [x] Add distinct `pre_workout` validation across schemas, recipe tags, candidates, plans, and swaps; retain `snack`.
- [x] Add migration `20261026_0019` expanding only the meal-item type check; retain one head.
- [x] Expand the repeatable development catalog to ten recipes per required meal type with complete structured nutrition and executable steps.
- [x] Provide at least five dairy-free and gluten-free recipes per required meal type.
- [x] Explicitly review all twelve fixture ingredient specifications with canonical allergen lists and nonblank source references.
- [x] Verify exact four-slot frontend profile with a 201 integration test and fail-closed allergy/solver regression tests.
- [x] Test owned plan-log/snack GET responses and explicit recipe swap selection through normal filtering.
- [x] Document exact API requests, catalog counts, nutrition provenance, and review/cross-contact limitations.
- [x] Run affected regression tests; correct catalog-size assumptions and rerun all 59 AI/P0 tests successfully.
- [x] Verify upgrade from `20261021_0018` to the single `20261026_0019` head on isolated and existing development databases.
- [x] Run full `pytest -q`: 379 passed in 519.49s (0:08:39).
- [x] Run `git diff --check` and review final status without committing or pushing.

## Frontend Nutrition and Tracking Batch

- [x] Add owned daily water/fruit-veg/sleep records with unique user/date, bounded finite inputs, full PUT upserts, history, GET/delete, and UTC+1 tolerance.
- [x] Include daily metrics in existing account export and deletion cascades.
- [x] Add only migration `20261028_0020` following `20261026_0019`; verify upgrade/downgrade/re-upgrade with one head and preserved catalog rows.
- [x] Add explicit modeled `added_sugar` grams to every development food and deterministic recipe calculations; retain fiber and all 16 completeness checks.
- [x] Preserve known non-target nutrients in solver/plan/actual snapshots without inventing optimization targets or rewriting history.
- [x] Extend intake with nullable fiber/added-sugar fields; use actual food snack snapshots and unknown values for macro-only custom snacks.
- [x] Keep generic insight items and add deterministic, unit-tested, coverage-adjusted nutrition scores with target provenance and unavailable states.
- [x] Run daily-metrics targeted tests: 17 passed.
- [x] Run nutrient/intake/solver/meal-log/P0 targeted tests, including incomplete recipe corrections: 59 passed as part of the final 156-test affected regression run.
- [x] Run insights/scoring/existing nutrition targeted tests, including concurrent intake removal: 80 passed.
- [x] Run all affected tracking/nutrition/insights/P0 tests together: 156 passed in 156.34s.
- [x] Document exact API shapes, scoring formulas, input bounds, fixture modeling, null behavior, and limitations.
- [x] Run final full `pytest -q`: 476 passed in 716.62s (0:11:56), including concurrent insight removal and incomplete recipe snapshot regressions.
- [x] Verify `alembic heads` is solely `20261028_0020`, run `git diff --check`, and review status without committing or pushing.
