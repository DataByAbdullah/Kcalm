# Kcalm Database Schema

## Schema Goals

The database must support deterministic nutrition calculation, solver-based meal planning, user preferences, meal swaps, logging, grocery lists, AI auditability, and Postman-friendly seed data.

Nutrition data must always preserve source attribution. Historical plans must remain reproducible even after targets, recipes, or nutrient data change.

## Final MVP Integrity Notes

### Progress and Account Extension Schema

The current head is `20261028_0020`, following the P0 `20261026_0019` meal-type migration
and the original six progress/account migrations after `fcdf61504ece`.
Existing migrations and unrelated email/profile indexes and constraints are untouched.

| Table | Fields and Relationships |
| --- | --- |
| `weight_logs` | UUID, user FK CASCADE, log date, finite 20-500 kg weight, timestamps; unique user/date |
| `step_logs` | UUID, user FK CASCADE, log date, integer steps 0-200000, timestamps; unique user/date |
| `daily_metrics` | UUID, user FK CASCADE, log date, integer water_glasses 0-100, float fruit_veg_servings 0-100, float sleep_hours 0-24, UTC timestamps; unique user/date |
| `habits` | UUID, user FK CASCADE/index, nonblank name, nullable description, start date, active, timestamps |
| `habit_completions` | UUID, habit FK CASCADE, date, timestamps; unique habit/date |
| `notifications` | UUID, user FK CASCADE, event key, kind, title/message snapshots, nullable UTC read_at, timestamps; unique user/event and user/created index |

`users.token_version` is non-null integer default 0 for revocation after password changes.
`foods.allergen_codes` is nullable JSON and `foods.allergen_reference` is nullable text
up to 1000 characters. Null means unknown; a reviewed empty code list has explicit source
attribution. The nutrition/tracking batch adds explicit `added_sugar` gram rows to fixture
foods and calculated recipes, not new nutrient columns. Existing `full_name`, `membership_tier`,
`target_weight_kg`, standalone snack logs, and nutrient snapshots are reused.
All new owned records are covered by account deletion cascades and JSON export.
Achievements/insights are calculated on read and have no fake-progress persistence tables.

The original MVP hardening head was `20261013_0012`; later extensions are listed above.

Important integrity boundaries:

- User-owned data cascades from `users` where it is safe to remove account-owned working data: profiles, daily plans, weekly plans, grocery lists, meal logs, and execution sessions.
- Historical nutrition stability is achieved through snapshots rather than live joins for saved plans, grocery lists, meal logs, adaptive planning inputs, and recipe execution sessions.
- Food and recipe source tables remain mutable development/admin data; persisted plan/log/grocery/execution records store the values required to explain historical results.
- Meal plan item nutrient snapshots, meal plan micronutrient target snapshots, grocery ingredient snapshots, meal log nutrient snapshots, and recipe execution step snapshots must not be recalculated from mutable source rows during read APIs.
- OpenAI output is not persisted as nutrition-bearing data and does not write to `foods`, `food_nutrients`, `recipe_nutrients`, `meal_plan_item_nutrients`, or `meal_log_nutrients`.

## Core Identity Tables

### `users`

Stores account identity.

Key columns:

- `id`
- `email`
- `password_hash`
- `is_active`
- `created_at`
- `updated_at`

Relationships:

- One user has one or many profile versions.
- One user has many target sets, meal plans, logs, grocery lists, and AI interactions.

### `refresh_tokens` — deferred

Stores refresh token hashes and revocation metadata if first-party auth is implemented.

Relationships:

- Many refresh tokens belong to one user.

## Profile and Preference Tables

### `user_profiles`

Stores biometric and lifestyle data.

Key columns:

- `id`
- `user_id`
- `sex`
- `age`
- `height_cm`
- `weight_kg`
- `activity_level`
- `goal`
- `target_rate`
- `max_cooking_minutes`
- `meals_per_day`
- `created_at`
- `updated_at`

Relationships:

- One profile belongs to one user.
- One user can have only one profile.
- Profile values are data capture only; nutrition targets are calculated in a later milestone.

### `activity_levels`

Stores supported activity multipliers.

Key columns:

- `id`
- `key`
- `label`
- `tdee_multiplier`

### `user_allergies`

Stores normalized allergy names for a user.

Key columns:

- `id`
- `user_id`
- `name`
- `created_at`
- `updated_at`

Supported allergy codes are now hard candidate constraints based on reviewed food
allergen metadata. Unknown codes and missing reviews exclude candidates.

### `user_dietary_restrictions`

Stores normalized dietary restriction names for a user.

Key columns:

- `id`
- `user_id`
- `name`
- `created_at`
- `updated_at`

Relationships:

- Many dietary restrictions belong to one user.

### `user_preferred_foods`

Stores normalized preferred food names for a user.

Key columns:

- `id`
- `user_id`
- `name`
- `created_at`
- `updated_at`

Preferred foods are soft preferences, not safety constraints.

### `user_disliked_foods`

Stores normalized disliked food names for a user.

Key columns:

- `id`
- `user_id`
- `name`
- `created_at`
- `updated_at`

Disliked foods are soft constraints unless a future request marks them as exclusions.

### `user_equipment`

Stores normalized kitchen equipment names for a user.

Key columns:

- `id`
- `user_id`
- `equipment`
- `created_at`
- `updated_at`

### Deferred Canonical Tables

Canonical restriction, equipment, and preference tag tables are deferred until they are needed for solver metadata and seed catalogs.

Key columns:

- `id`
- `user_id`
- `preference_tag_id`
- `weight`
- `source`

Relationships:

- Many weighted preferences belong to one user.

## Nutrition Reference Tables

### `nutrients`

Canonical nutrient definitions.

Key columns:

- `id`
- `external_id`
- `name`
- `unit`
- `nutrient_type`
- `is_tracked`

Examples:

- Calories.
- Protein.
- Carbohydrates.
- Fat.
- Fiber.
- Sodium.
- Potassium.
- Calcium.
- Iron.
- Vitamin D.

### `nutrient_reference_values`

Stores DRI/RDA targets by demographic group.

Key columns:

- `id`
- `nutrient_id`
- `sex`
- `age_min`
- `age_max`
- `life_stage`
- `target_amount`
- `upper_limit_amount`
- `unit`
- `source`
- `source_version`

Relationships:

- Many reference values belong to one nutrient.

### `nutrition_target_sets`

Versioned target snapshots for users.

Key columns:

- `id`
- `user_id`
- `profile_id`
- `status`
- `calories_kcal`
- `protein_g`
- `carbs_g`
- `fat_g`
- `fiber_g`
- `calculation_method`
- `bmr_kcal`
- `tdee_kcal`
- `goal_adjustment_kcal`
- `created_at`
- `confirmed_at`

Relationships:

- One target set has many micronutrient targets.
- Meal plans reference the target set used during generation.

### `nutrition_target_micronutrients`

Micronutrient targets attached to a target set.

Key columns:

- `id`
- `target_set_id`
- `nutrient_id`
- `target_amount`
- `minimum_amount`
- `upper_limit_amount`
- `unit`

## Food Data Tables

### `foods`

Stores internal structured food records.

Key columns:

- `id`
- `name`
- `source`
- `source_food_id`
- `category`
- `description`
- `created_at`
- `updated_at`

Relationships:

- One food has many nutrient values.
- One food has many serving conversions.
- Recipe ingredients reference foods for deterministic recipe nutrition calculation.
- USDA imports use `source = usda` and `source_food_id = <FDC ID>`.

Constraints:

- `source` is one of `internal`, `usda`, or `licensed`.
- `source_food_id` may be null for manual development foods.
- `source` and `source_food_id` are unique when `source_food_id` is present.
- `name` and `category` cannot be blank.
- `name` and `category` are indexed for lookup and filtering.

USDA import behavior:

- A USDA food is imported at most once because `source` plus `source_food_id` identifies the external record.
- Duplicate USDA import requests return the existing local `foods` row instead of inserting another record.
- Search results from USDA are not persisted until an explicit import request succeeds.
- Imported USDA food descriptions include source attribution metadata such as data type and brand owner when present.

### `food_nutrients`

Stores normalized nutrient values per 100 grams.

Key columns:

- `id`
- `food_id`
- `nutrient_code`
- `nutrient_name`
- `amount`
- `unit`
- `created_at`
- `updated_at`

Relationships:

- Many nutrient values belong to one food.

Constraints:

- Nutrient values are normalized per 100g.
- `amount` must be non-negative.
- `nutrient_code`, `nutrient_name`, and `unit` cannot be blank.
- One food cannot have duplicate rows for the same `nutrient_code`.

USDA nutrient mapping:

- USDA nutrient IDs and names are mapped centrally in `app/integrations/usda_nutrients.py`.
- The current import mapping supports `calories`, `protein`, `carbohydrates`, `fat`, `fiber`, `calcium`, `iron`, `magnesium`, `potassium`, `sodium`, `vitamin_a`, `vitamin_c`, `vitamin_d`, `vitamin_b12`, and `folate`.
- Unit conversion is deterministic for compatible `kcal`, `g`, `mg`, and `mcg` units.
- Unsupported USDA nutrient units are skipped rather than converted by assumption.
- Imported nutrient rows use USDA `foodNutrients` values as Kcalm's per-100g source and do not import serving-based `labelNutrients`.

Current nutrient code examples:

- `calories`
- `protein`
- `carbohydrates`
- `fat`
- `fiber`
- `added_sugar`
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

### `food_servings`

Stores human serving labels and gram conversions.

Key columns:

- `id`
- `food_id`
- `serving_name`
- `grams`
- `created_at`
- `updated_at`

Relationships:

- Many serving options belong to one food.

Constraints:

- `grams` must be greater than zero.
- `serving_name` cannot be blank.
- One food cannot have duplicate rows for the same `serving_name`.

USDA serving import behavior:

- USDA `foodPortions` rows become serving rows only when a reliable `gramWeight` is present.
- Branded `servingSize` is imported only when the unit is grams.
- A `100 g` serving is added consistently for USDA imports.
- Nutrition values are not duplicated or recalculated into serving rows.

### `food_sources` — deferred

Future canonical nutrition data provider table for USDA and licensed imports.

### `food_import_batches` — deferred

Future import tracking table for USDA or licensed provider batches.

### `units`

Canonical units.

Key columns:

- `id`
- `key`
- `label`
- `dimension`

### `unit_conversions`

Stores deterministic conversions between units, optionally food-specific.

Key columns:

- `id`
- `from_unit_id`
- `to_unit_id`
- `food_id`
- `factor`
- `source`

## Recipe Tables

### `recipes`

Stores structured recipes.

Key columns:

- `id`
- `name`
- `description`
- `servings`
- `prep_time_minutes`
- `cook_time_minutes`
- `total_time_minutes`
- `difficulty`
- `instructions_summary`
- `active`
- `source`
- `created_at`
- `updated_at`

Relationships:

- One recipe has many ingredients.
- One recipe has many steps.
- One recipe has many tag links.
- One recipe has many required equipment rows.
- One recipe has many calculated nutrient rows.

Constraints:

- `name` cannot be blank.
- `servings` must be greater than zero.
- Prep, cook, and total times must be non-negative.
- `total_time_minutes` must equal `prep_time_minutes + cook_time_minutes`.
- `active` supports soft archiving instead of destructive delete.
- Recipes tagged `quick` are validated in the service layer to require `total_time_minutes <= 20`.

### `recipe_ingredients`

Stores recipe ingredient quantities linked to verified foods.

Key columns:

- `id`
- `recipe_id`
- `food_id`
- `quantity_grams`
- `display_quantity`
- `display_unit`
- `preparation_note`
- `position`
- `created_at`
- `updated_at`

Relationships:

- Many ingredients belong to one recipe.
- Each nutrition-bearing ingredient references one local `foods` row.

Constraints:

- `quantity_grams` is the canonical calculation quantity and must be greater than zero.
- Display quantity/unit are optional UI labels only.
- `(recipe_id, position)` is unique so ingredient ordering is deterministic.
- Food nutrients remain the source of truth for all recipe nutrition.

### `recipe_steps`

Stores cooking instructions and timer data.

Key columns:

- `id`
- `recipe_id`
- `position`
- `instruction`
- `phase`
- `duration_seconds`
- `timer`
- `timer_seconds`
- `cue_action`
- `animation_key`
- `media_asset_key`
- `visual_cue`
- `created_at`
- `updated_at`

Constraints:

- `position` must be positive.
- `instruction` cannot be blank.
- `phase` is one of `prep`, `cook`, `rest`, `assemble`, or `serve`.
- `duration_seconds` must be null or non-negative.
- `timer_seconds` must be null or non-negative.
- `(recipe_id, position)` is unique so step ordering is deterministic.
- `timer` stores whether an explicit timer is required; `timer_seconds` stores the explicit timer duration when available.
- `duration_seconds` is a step-duration estimate and is intentionally separate from `timer_seconds`.
- Media and animation fields are nullable placeholders for future clients; the backend does not generate or host animations.

### `recipe_tags`

Stores canonical recipe tag keys.

Key columns:

- `id`
- `name`
- `created_at`
- `updated_at`

Constraints:

- `name` cannot be blank.
- `name` is unique.

Supported MVP tags:

- `quick`
- `vegetarian`
- `vegan`
- `dairy_free`
- `gluten_free`
- `high_protein`
- `breakfast`
- `lunch`
- `dinner`
- `snack`

Tags are explicit structured data. Dietary safety is not inferred from recipe names.

### `recipe_tag_links`

Join table between recipes and tags.

Key columns:

- `id`
- `recipe_id`
- `tag_id`
- `created_at`
- `updated_at`

Constraints:

- `(recipe_id, tag_id)` is unique.
- Rows cascade when a recipe is archived/deleted physically in a future maintenance operation.

### `recipe_equipment`

Stores required equipment keys per recipe.

Key columns:

- `id`
- `recipe_id`
- `equipment`
- `created_at`
- `updated_at`

Constraints:

- `equipment` cannot be blank.
- `(recipe_id, equipment)` is unique.
- Equipment uses the current user-profile vocabulary style. Supported MVP values are `oven`, `stovetop`, `microwave`, `blender`, `air_fryer`, and `slow_cooker`.

### `recipe_nutrients`

Stores deterministic recipe nutrition totals and per-serving amounts.

Key columns:

- `id`
- `recipe_id`
- `nutrient_code`
- `nutrient_name`
- `total_amount`
- `per_serving_amount`
- `unit`
- `missing_ingredient_count`
- `complete`
- `created_at`
- `updated_at`

Relationships:

- Many calculated nutrients belong to one recipe.

Constraints:

- Amounts must be non-negative.
- `nutrient_code`, `nutrient_name`, and `unit` cannot be blank.
- `(recipe_id, nutrient_code)` is unique.

Calculation strategy:

- Recipe nutrients are persisted for future solver performance.
- Values are recalculated transactionally whenever recipe ingredients or serving count change.
- Clients never submit authoritative recipe nutrient numbers.
- Formula: `food_nutrient_per_100g * quantity_grams / 100`.
- `total_amount` is the sum across ingredients.
- `per_serving_amount` is `total_amount / recipe.servings`.

Missing nutrient behavior:

- Known ingredient nutrient values are summed.
- Missing food nutrient rows are not invented.
- `missing_ingredient_count` records how many ingredients lacked each nutrient.
- `complete = false` when any ingredient lacks that nutrient.

### Candidate filtering storage note

The Recipe Candidate Filtering / Constraint Preparation milestone does not add new tables. The preview service reads existing profile and recipe tables:

- `user_profiles`
- `user_equipment`
- `user_dietary_restrictions`
- `user_allergies`
- `user_disliked_foods`
- `user_preferred_foods`
- `recipes`
- `recipe_ingredients`
- `recipe_tags`
- `recipe_tag_links`
- `recipe_equipment`
- `recipe_nutrients`

Candidate preview output is derived at request time and is not persisted. Daily solver preview output also remains non-persistent; only `POST /api/v1/meal-plans` writes meal-plan rows.

## Recipe Execution Tables

Recipe execution stores immutable cooking-session snapshots for future mobile recipe-player clients. Execution state is separate from recipe CRUD, meal-plan persistence, meal swaps, and meal logging.

### `recipe_execution_sessions`

Stores one user-owned cooking execution session.

Key columns:

- `id`
- `user_id`
- `recipe_id`
- `meal_plan_id`
- `meal_plan_item_id`
- `recipe_name_snapshot`
- `servings`
- `status`
- `current_step_index`
- `total_estimated_time_minutes`
- `required_equipment_snapshot`
- `ingredient_summary_snapshot`
- `started_at`
- `completed_at`
- `created_at`
- `updated_at`

Relationships:

- One execution session belongs to one user.
- One execution session may reference a recipe.
- One execution session may reference a meal plan and meal-plan item.
- One execution session has many step snapshots.

Constraints and indexes:

- `status` is `not_started`, `in_progress`, `completed`, or `abandoned`.
- `servings` must be greater than zero.
- `current_step_index` must be non-negative.
- `total_estimated_time_minutes` must be null or non-negative.
- Lookup indexes cover `user_id`, `recipe_id`, `meal_plan_id`, `meal_plan_item_id`, and `status`.
- A partial unique index prevents more than one active `not_started` or `in_progress` session for the same `meal_plan_item_id`.

Snapshot behavior:

- `recipe_name_snapshot` stores the name at execution start.
- `required_equipment_snapshot` stores recipe-level equipment names.
- `ingredient_summary_snapshot` stores recipe or meal-plan-item ingredient quantities as JSON for client display.
- Completed and abandoned sessions remain historical records.

### `recipe_execution_step_snapshots`

Stores ordered immutable step snapshots for an execution session.

Key columns:

- `id`
- `execution_session_id`
- `recipe_step_id`
- `step_index`
- `recipe_step_position`
- `instruction_snapshot`
- `phase`
- `duration_seconds`
- `timer_required`
- `timer_seconds`
- `completed`
- `completed_at`
- `equipment_snapshot`
- `ingredient_references_snapshot`
- `cue_action`
- `animation_key`
- `media_asset_key`
- `visual_cue`
- `timer_started_at`
- `timer_completed_at`
- `created_at`
- `updated_at`

Relationships:

- Many step snapshots belong to one execution session.
- A snapshot may retain a nullable reference to the source `recipe_steps.id`, but the snapshot fields are authoritative for historical reads.

Constraints:

- `step_index` is zero-based and non-negative.
- `recipe_step_position` preserves the source recipe's positive one-based position.
- `instruction_snapshot` cannot be blank.
- `phase` is one of `prep`, `cook`, `rest`, `assemble`, or `serve`.
- Duration and timer seconds must be null or non-negative.
- `(execution_session_id, step_index)` is unique.

Timer semantics:

- `duration_seconds` estimates total step duration.
- `timer_required` and `timer_seconds` represent explicit timers.
- Server-side countdown jobs are not modeled; mobile clients render countdown UI.

Limitations:

- Step-level ingredient and equipment references are currently JSON placeholders because recipe steps do not yet store structured step-to-ingredient mappings.
- Starting execution from a meal-plan item snapshots current recipe steps at execution start; meal plans do not yet store step snapshots.

### `recipe_nutrition_snapshots` — deferred

Future versioned snapshots for immutable historical meal plans.

### `recipe_nutrition_snapshot_nutrients` — deferred

Future micronutrient rows attached to versioned recipe nutrition snapshots.

## Meal Planning Tables

### `weekly_meal_plans`

Stores persisted seven-day weekly plan containers.

Key columns:

- `id`
- `user_id`
- `start_date`
- `end_date`
- `status`
- `created_at`
- `updated_at`

Relationships:

- One weekly meal plan belongs to one user.
- One weekly meal plan has many generated daily `meal_plans`.

Constraints:

- `status` is `generated` or `archived`.
- `end_date` must be on or after `start_date`.
- Service logic derives `end_date = start_date + 6 days`.
- A partial unique index on `(user_id, start_date, end_date)` where `status = 'generated'` prevents duplicate active weeks for the same user/date range.

Archive behavior:

- Weekly archive is a soft status change.
- The current implementation also archives the generated member daily plans.
- Unrelated standalone daily plans are not changed.

### `meal_plans`

Stores persisted one-day generated meal plans.

Key columns:

- `id`
- `user_id`
- `weekly_plan_id`
- `plan_date`
- `status`
- `solver_status`
- `calorie_target`
- `protein_target`
- `carbohydrate_target`
- `fat_target`
- `within_preferred_tolerance`
- `objective_value`
- `solve_time_seconds`
- `candidate_count`
- `created_at`
- `updated_at`

Relationships:

- One meal plan has many meal plan items.
- One meal plan has many micronutrient target snapshots.
- One meal plan belongs to one user.
- One meal plan may belong to one weekly meal plan.

Constraints:

- `status` is `generated` or `archived`.
- `solver_status` is `optimal` or `feasible`; infeasible solver results are never persisted.
- Macro targets are positive.
- `objective_value` uses a bigint because OR-Tools objectives can exceed 32-bit integer range.
- `candidate_count` and `solve_time_seconds` must be non-negative.
- A partial unique index on `(user_id, plan_date)` where `status = 'generated'` enforces one active generated plan per user per day while allowing archived historical plans.
- `weekly_plan_id` is nullable so standalone daily plans remain supported.

### `meal_plan_items`

Stores selected recipe portions in a persisted one-day plan.

Key columns:

- `id`
- `meal_plan_id`
- `meal_type`
- `recipe_id`
- `recipe_name_snapshot`
- `servings`
- `position`
- `created_at`
- `updated_at`

Relationships:

- Many plan items belong to one meal plan.
- Each item references a recipe.
- One item has many nutrient contribution snapshots.
- One item has many ingredient quantity snapshots for grocery preview.

Constraints:

- `meal_type` is `breakfast`, `lunch`, `pre_workout`, `dinner`, or `snack`.
- Additive migration `20261026_0019` expands only `ck_meal_plan_items_meal_type_valid`; no column, index, user/email constraint, or historical item is rewritten. Downgrade requires explicitly handling existing pre-workout items before narrowing the check.
- `servings` must be greater than zero.
- `position` must be greater than zero.
- `recipe_name_snapshot` cannot be blank.
- `(meal_plan_id, position)` is unique for deterministic response ordering.

Snapshot behavior:

- `recipe_name_snapshot` stores the recipe name selected at generation time.
- Saved plan responses use this snapshot so later recipe edits do not rewrite historical plan names.

### `meal_plan_item_nutrients`

Stores nutrient contribution snapshots for each persisted plan item.

Key columns:

- `id`
- `meal_plan_item_id`
- `nutrient_code`
- `nutrient_name`
- `amount`
- `unit`
- `created_at`
- `updated_at`

Relationships:

- Many nutrient snapshots belong to one meal plan item.

Constraints:

- `amount` must be non-negative.
- `nutrient_code`, `nutrient_name`, and `unit` cannot be blank.
- `(meal_plan_item_id, nutrient_code)` is unique.

Usage:

- Daily totals are reconstructed from these item snapshots.
- Persisted plan nutrition does not change when source recipe nutrients are recalculated later.

### `meal_plan_item_ingredients`

Stores ingredient quantity snapshots for each persisted plan item.

Key columns:

- `id`
- `meal_plan_item_id`
- `food_id`
- `food_name_snapshot`
- `quantity_grams`
- `created_at`

Relationships:

- Many ingredient snapshots belong to one meal plan item.
- Each ingredient snapshot references one stable `foods.id`.

Constraints:

- `quantity_grams` must be greater than zero.
- `food_name_snapshot` cannot be blank.
- `(meal_plan_item_id, food_id)` is unique.

Usage:

- Weekly grocery preview aggregates these rows by `food_id`.
- Snapshot quantity is calculated when the daily plan item is persisted:

```text
recipe_ingredient.quantity_grams * meal_plan_item.servings
```

- Ingredient snapshots are persisted during meal swaps for replacement items as well.
- Grocery preview does not read live recipe ingredients, so recipe edits do not change historical weekly grocery totals.
- Older or manually associated plans without these snapshots return `GROCERY_SNAPSHOT_MISSING` rather than silently mixing historical and live recipe behavior.

### `meal_plan_micronutrient_targets`

Stores micronutrient target snapshots used when the plan was generated.

Key columns:

- `id`
- `meal_plan_id`
- `nutrient_code`
- `nutrient_name`
- `target`
- `unit`
- `minimum_target`
- `upper_limit`
- `upper_limit_type`
- `created_at`
- `updated_at`

Relationships:

- Many micronutrient target snapshots belong to one meal plan.

Constraints:

- `target` must be greater than zero.
- `minimum_target` and `upper_limit` must be null or greater than zero.
- `nutrient_code`, `nutrient_name`, and `unit` cannot be blank.
- `(meal_plan_id, nutrient_code)` is unique.

Usage:

- Micronutrient coverage for a saved plan is calculated from these target snapshots and the saved item nutrient snapshots.
- Saved plan targets do not change when a user's profile changes later.

### `meal_plan_nutrition_totals` — deferred

Future materialized totals for a day or whole plan. The current implementation derives totals from `meal_plan_item_nutrients` at read time.

Key columns:

- `id`
- `meal_plan_id`
- `date`
- `calories_kcal`
- `protein_g`
- `carbs_g`
- `fat_g`
- `fiber_g`
- `calculated_at`
- `validation_status`

### `meal_plan_nutrition_total_nutrients` — deferred

Future micronutrient total rows attached to materialized plan totals.

### `solver_runs` — deferred

Future optimization diagnostics table. The current `meal_plans` row stores MVP solver summary fields directly.

Key columns:

- `id`
- `user_id`
- `meal_plan_id`
- `solver_type`
- `status`
- `objective_value`
- `duration_ms`
- `candidate_count`
- `constraints_summary`
- `infeasibility_reasons`
- `created_at`

### `meal_swaps` — deferred

Future swap attempts and applied swaps.

Current single-meal swap behavior does not add a table. The active `meal_plan_items` row is updated in place, its old nutrient snapshot rows are replaced transactionally, and locked meal item snapshots are left unchanged. Full swap audit/version history is deferred to this future table.

Key columns:

- `id`
- `meal_plan_id`
- `original_item_id`
- `replacement_recipe_id`
- `replacement_servings`
- `status`
- `request_constraints`
- `nutrition_delta`
- `solver_run_id`
- `created_at`
- `applied_at`

## Logging and Adaptation Tables

### `meal_logs`

Stores one current actual intake log for a persisted meal-plan item.

Key columns:

- `id`
- `user_id`
- `meal_plan_id`
- `meal_plan_item_id`
- `log_date`
- `log_type`
- `status`
- `source_type`
- `recipe_id`
- `food_id`
- `quantity_grams`
- `servings`
- `nutrient_complete`
- `created_at`
- `updated_at`

Constraints and indexes:

- `log_type` is `ate_as_planned` or `corrected`.
- `status` is currently `active`.
- `source_type` is nullable for ate-as-planned logs and otherwise `food` or `recipe`.
- Ate-as-planned logs cannot store correction source fields.
- Food corrections require `food_id` and positive `quantity_grams`.
- Recipe corrections require `recipe_id` and positive `servings`.
- `user_id`, `meal_plan_id`, and `meal_plan_item_id` cascade when parent records are removed.
- Partial unique index `uq_meal_logs_meal_plan_item_id_active` allows one active/current log per meal-plan item.

Behavior:

- Re-logging an item updates the active row and replaces nutrient snapshots.
- Reset deletes the active row.
- Archived meal plans cannot receive new logs.
- Logging does not update planned meal-plan item nutrient snapshots or target snapshots.

### `meal_log_nutrients`

Stores actual consumed nutrient snapshots for meal logs.

Key columns:

- `id`
- `meal_log_id`
- `nutrient_code`
- `nutrient_name`
- `amount`
- `unit`
- `created_at`
- `updated_at`

Constraints and indexes:

- `meal_log_id` references `meal_logs.id` with cascade delete.
- `amount >= 0`.
- `nutrient_code`, `nutrient_name`, and `unit` must be non-blank.
- Unique index on `meal_log_id + nutrient_code`.

Nutrition source rules:

- Ate-as-planned logs copy `meal_plan_item_nutrients`.
- Corrected food logs calculate from `food_nutrients` per 100g and `quantity_grams`.
- Corrected recipe logs calculate from `recipe_nutrients.per_serving_amount` and `servings`.
- Missing nutrient values are not invented; absent structured nutrient rows remain absent from the actual snapshot.

Daily actual totals:

- Calculated on read by summing active `meal_log_nutrients`.
- Unlogged meal-plan items do not count as eaten.
- Planned-vs-actual summaries compare actual totals with immutable planned totals and saved target snapshots.

### `meal_plan_adaptations`

Stores historical traceability metadata for adaptive next-day plans.

This table does not store actual meal logs or replace meal-plan target snapshots. It explains why the generated adaptive plan's saved targets differ from the user's normal profile-derived targets.

Key columns:

- `id`
- `meal_plan_id`
- `source_meal_plan_id`
- `policy_version`
- `base_calorie_target`
- `source_actual_calories`
- `source_calorie_deviation`
- `compensation_fraction`
- `compensation_amount`
- `adjusted_calorie_target`
- `base_protein_target`
- `base_carbohydrate_target`
- `base_fat_target`
- `adjusted_protein_target`
- `adjusted_carbohydrate_target`
- `adjusted_fat_target`
- `safety_cap_applied`
- `created_at`
- `updated_at`

Constraints and indexes:

- `meal_plan_id` references the generated adaptive `meal_plans.id` with cascade delete.
- `source_meal_plan_id` references the logged source `meal_plans.id` with cascade delete.
- `meal_plan_id` is unique so one generated plan has at most one adaptation snapshot.
- `policy_version` is non-blank.
- Calorie, protein, and fat targets must be positive.
- Carbohydrate targets must be non-negative.
- `compensation_fraction` must be between `0` and `1`.
- Lookup indexes cover `meal_plan_id`, `source_meal_plan_id`, and `policy_version`.

Policy fields:

- Current `policy_version` is `adaptive_v1`.
- Current `compensation_fraction` is `0.25`.
- `safety_cap_applied` is true when the max adjustment or minimum adjusted calorie bound changed the raw compensation amount.

### `daily_nutrition_logs`

Deferred. The current implementation calculates daily actual totals from active meal logs at read time instead of materializing them.

## Grocery Tables

Smart grocery lists persist deterministic weekly grocery aggregation into user-editable rows. Generated list items are sourced from `meal_plan_item_ingredients`, not live `recipe_ingredients`, USDA calls, OpenAI, or retailer APIs.

### `grocery_lists`

Stores one user-owned grocery list generated from a weekly meal plan.

Key columns:

- `id`
- `user_id`
- `weekly_plan_id`
- `status`
- `generated_at`
- `created_at`
- `updated_at`

Constraints and indexes:

- `status` is `active` or `archived`.
- `user_id` references `users.id` with cascade delete.
- `weekly_plan_id` references `weekly_meal_plans.id` with cascade delete.
- Partial unique index `uq_grocery_lists_weekly_plan_id_active` prevents more than one active list for the same weekly plan.
- Lookup indexes cover `user_id`, `weekly_plan_id`, and `status`.

Relationships:

- One grocery list belongs to one user.
- One grocery list belongs to one weekly meal plan.
- One grocery list has many grocery list items.

### `grocery_list_items`

Stores generated and manual grocery rows for a list.

Key columns:

- `id`
- `grocery_list_id`
- `food_id`
- `food_name_snapshot`
- `quantity`
- `unit`
- `quantity_grams`
- `category`
- `checked`
- `manually_added`
- `created_at`
- `updated_at`

Constraints and indexes:

- `grocery_list_id` references `grocery_lists.id` with cascade delete.
- `food_id` references `foods.id` and is nullable for manual items.
- `quantity > 0`.
- `quantity_grams` is nullable, but when present must be greater than `0`.
- `food_name_snapshot` and `unit` must be non-blank.
- `category` is one of `produce`, `meat_seafood`, `dairy`, `grains`, `pantry`, `frozen`, or `other`.
- Partial unique index `uq_grocery_list_items_list_food_generated` prevents duplicate generated rows for the same `food_id` inside one list.
- Lookup indexes cover `grocery_list_id`, `food_id`, `category`, and `checked`.

Relationships:

- Many grocery items belong to one grocery list.
- Generated grocery items may reference one `foods` row.
- Manual grocery items use `food_id = null` and keep user-provided text/quantity.

Generation semantics:

- Automatic items are aggregated by stable `food_id`.
- Repeated Food IDs merge by summing grams.
- Different Food IDs do not merge even when their snapshots have the same display name.
- Generated items store `food_name_snapshot` for historical consistency.
- Generated quantities use canonical grams: `quantity`, `unit = 'g'`, and `quantity_grams`.
- Grocery categories are deterministically mapped from existing Food categories where known, with unknown categories stored as `other`.

Regeneration semantics:

- Regeneration deletes and recreates automatic items from the current persisted weekly meal-plan ingredient snapshots.
- Manual items are preserved.
- Automatic checked state is preserved by Food ID.
- Generated item quantity edits are reset to snapshot totals during regeneration.
- Grocery list edits do not propagate to meal plans, recipes, foods, or snapshots.

## AI Audit Tables

### `ai_interactions`

Stores auditable AI requests and responses with privacy controls.

Key columns:

- `id`
- `user_id`
- `interaction_type`
- `model`
- `prompt_version`
- `input_hash`
- `redacted_input`
- `validated_output`
- `status`
- `error_message`
- `created_at`

Usage:

- Preference extraction.
- Constraint extraction.
- Target explanation.
- Meal plan explanation.
- Swap explanation.

AI interactions must not store or introduce nutrition source numbers.

## Relationship Summary

- `users` -> `user_profiles` -> `nutrition_target_sets`
- `users` -> restrictions, equipment, preferences
- `nutrition_target_sets` -> macro columns and micronutrient target rows
- `food_sources` -> `food_import_batches` -> `foods` -> `food_nutrients`
- `recipes` -> `recipe_ingredients` -> `foods`
- `recipes` -> `recipe_steps`, tags, equipment, nutrition snapshots
- `users` -> `recipe_execution_sessions` -> `recipe_execution_step_snapshots`
- `recipe_execution_sessions` -> optional `recipes`, `meal_plans`, and `meal_plan_items`
- `weekly_meal_plans` -> `meal_plans`
- `meal_plans` -> `meal_plan_items` -> `recipes`
- `meal_plan_items` -> `meal_plan_item_nutrients`
- `meal_plan_items` -> `meal_plan_item_ingredients` -> `foods`
- `meal_plans` -> `meal_plan_micronutrient_targets`
- `meal_plans` -> `meal_plan_adaptations` for adaptive next-day traceability
- `meal_plans` -> deferred nutrition totals, solver runs, swaps
- `meal_plan_items` -> `meal_logs`
- `meal_logs` -> `meal_log_nutrients`
- `weekly_meal_plans` -> `grocery_lists` -> `grocery_list_items`
- `users` -> `ai_interactions`

## Important Constraints

- Recipe ingredients must reference verified foods before a recipe can be solver-eligible.
- Solver-eligible recipes must have calculated nutrition snapshots.
- Current daily meal plans must store target snapshots directly and must not rely on mutable profile fields for historical reads.
- Applied swaps must revalidate the full day once swaps are implemented.
- AI output cannot write directly to nutrition-bearing tables.
