# Nutrition and Daily Tracking Batch

All routes use `/api/v1`, bearer authentication, and the existing API error envelope.
No AI or health recommendations are involved. This batch adds migration
`20261028_0020` after `20261026_0019`; it creates only `daily_metrics`. Nutrition
storage is already normalized, so added sugar needs no new database nutrient columns.

## Setup

```bash
alembic upgrade head
python -m app.scripts.seed_recipes
```

The seed command refreshes the twelve explicitly modeled food fixtures, then recalculates
the same 41 recipes with all 16 nutrient definitions. It is repeatable. Other foods are
not assigned guessed added-sugar values. Imported/user-authored foods need verified
added-sugar rows before their recipes can pass full-completeness filtering. The existing
USDA mapper is unchanged; it does not currently import `added_sugar`.

## Daily Metrics

| Method | Route | Result |
| --- | --- | --- |
| PUT | `/daily-metrics/{log_date}` | 200, create or replace owned record |
| GET | `/daily-metrics/{log_date}` | 200, record; missing record is 404 |
| GET | `/daily-metrics?from=2026-10-01&to=2026-10-28` | 200, paginated history |
| DELETE | `/daily-metrics/{log_date}` | 204; missing record is 404 |

PUT requires all three fields. Partial PUT is 422, PATCH is not supported (405), and
unknown fields are rejected. Values replace the date's entire record, not increment it.
Repeated PUTs retain the same ID and creation timestamp. Zero is a real recorded value;
GET of a missing day does not fabricate an all-zero record.

```json
{"water_glasses":8,"fruit_veg_servings":5,"sleep_hours":7.5}
```

Record response:

```json
{
  "id":"<uuid>",
  "log_date":"2026-10-28",
  "water_glasses":8,
  "fruit_veg_servings":5.0,
  "sleep_hours":7.5,
  "created_at":"<UTC timestamp>",
  "updated_at":"<UTC timestamp>"
}
```

History response is `{"items":[...],"total":1,"limit":100,"offset":0}`, newest date
first. Optional `from`/`to` are inclusive; `limit=1..365` defaults to 100, `offset>=0`
defaults to 0. Inverted ranges return `INVALID_DATE_RANGE`. Writes accept dates through
UTC today + one calendar day; later dates return `FUTURE_LOG_DATE`. Dates must be valid
ISO calendar dates. Single-date reads/history do not create records or validate them as writes.

Water is a strict integer 0-100. Servings are finite numeric values 0-100; sleep is finite
numeric 0-24 hours. Strings, booleans, nulls, NaN, and infinity are not valid inputs.
These are input-error bounds, not recommended consumption or sleep targets. Glass size
and serving size are user-entered units; no volume, hydration need, or medical meaning is
inferred. Missing/other-user records return `DAILY_METRICS_NOT_FOUND`; another user's
same-date PUT creates only that caller's record. Account export includes these records,
and account deletion removes them by the existing user-FK cascade.

## Fiber and Added Sugar Intake

`GET /nutrition/intake?from=2026-10-01&to=2026-10-28` still returns one object per calendar
day, including zero-intake dates. It adds two nullable fields without removing any macros:

```json
{
  "date":"2026-10-28",
  "calories":300.0,
  "protein_g":8.0,
  "carbs_g":50.0,
  "fat_g":6.0,
  "fiber_g":4.5,
  "added_sugar_g":2.0
}
```

Numbers above illustrate the response shape, not a generated meal or nutrition target.
Both new fields use grams. `added_sugar` is an explicit per-100g food nutrient and recipe
definition; calculations use the existing `amount * ingredient_grams / 100 / servings`
pipeline. No carbohydrate, total-sugar, or natural-sugar inference is performed.

Every development food explicitly supplies `added_sugar=0`: plain chicken breast, rice
cooked in water, whole egg, plain oats, unsweetened milk/yogurt, raw spinach, broccoli,
banana, unseasoned salmon, pure olive oil, and potato. This describes the development
specifications, not arbitrary commercial products or verified production nutrient data.
Existing fixture nutrient values remain unchanged. The added-sugar argument has no
default, so a future fixture must supply a value intentionally.

New plan/meal/snack snapshots carry the known added-sugar nutrient generically. Added
sugar has no invented optimization target and does not change the solver's objective.
Actual intake sums only active meal logs plus standalone snack records, never unlogged
planned meals. It reads snapshots, not mutable food or recipe values.

Unknown-data policy for each new field independently:

- No intake entries for a date: `0.0`, matching the existing endpoint's zero-day convention.
- Every consumed entry has a compatible gram snapshot: sum those recorded amounts.
- Any entry lacks that nutrient or has an incompatible unit: `null` for the entire day's
  field; known partial amounts are not presented as a complete daily total.
- Macro-only custom snacks remain macro-only: they have no fabricated fiber/added-sugar
  snapshots, and both daily fields become `null` on those days. Removing that snack can
  restore availability from the remaining snapshots.
- Food-based snacks copy actual structured food snapshots, including both nutrients when
  present. Old food/plan/log snapshots are not retroactively rewritten or filled with zeros.
- Recipe-based corrections copy only complete source nutrient rows. A calculated partial
  amount (including a zero placeholder marked incomplete) is not logged as a known amount.

Full recipe completeness now requires all 16 defined nutrients. Missing added sugar stays
`complete=false`, not a known zero. All seeded recipes remain complete after reseeding.

## Nutrition Insights

For Postman, set `base_url = http://127.0.0.1:8000/api/v1`, use
`Authorization: Bearer {{access_token}}` on every request and `Content-Type: application/json`
on PUT/POST. For a manual intake check on a date without other entries:

1. PUT `{{base_url}}/daily-metrics/2026-10-28` with the three-field example above;
   expect 200, then repeat and verify the same record ID.
2. GET that date and `{{base_url}}/daily-metrics?from=2026-10-28&to=2026-10-28`;
   expect the record and a one-item history. DELETE the date returns 204.
3. GET `{{base_url}}/foods?search=Banana` and copy the seeded banana ID.
4. POST `{{base_url}}/nutrition/snacks` with
   `{"log_date":"2026-10-28","food_id":"<banana UUID>","quantity_grams":100}`.
   Expect 201. GET `{{base_url}}/nutrition/intake?from=2026-10-28&to=2026-10-28`;
   the modeled banana snapshot supplies `fiber_g=2.6` and `added_sugar_g=0`.
5. Add a macro-only custom snack on that date using the existing POST schema. Both
   new intake fields become null; delete the custom snack to restore availability.
6. GET `{{base_url}}/insights?start_date=2026-10-28&end_date=2026-10-28` and inspect
   `nutrition_summary`. A snack-only date without logged plan items has unavailable
   scores (`meal_logging_unverified`, or `targets_unavailable` without targets).
   Logged plan dates use the exact formulas and completeness rules below.

`GET /insights?start_date=2026-10-01&end_date=2026-10-28` keeps all existing generic
`items`, date handling, ownership, and `logged_nutrition_days`. Its added field is:

```json
{
  "nutrition_summary": {
    "formula_version":"recorded_plan_alignment_v1",
    "nutrition_score":null,
    "unavailable_reason":"no_recorded_nutrition",
    "target_sources":[],
    "calorie_adherence":{
      "score":null,
      "average_actual_calories":null,
      "average_target_calories":null,
      "logged_days":0
    },
    "macro_balance":{
      "score":null,
      "protein_adherence_percent":null,
      "carbs_adherence_percent":null,
      "fat_adherence_percent":null
    },
    "data_completeness":{
      "logged_days":0,
      "days_in_range":28,
      "percentage":0.0,
      "scored_days":0,
      "unscored_days":0,
      "planned_meals":0,
      "logged_planned_meals":0,
      "meal_logging_percentage":null
    }
  }
}
```

### Exact Formulas

This is a product **target-alignment and logging-evidence metric**, not a medical,
clinical, dietary quality, or health score. Low scores can reflect underlogging.
The deterministic implementation is `app/nutrition/insights.py`.

For each recorded day `d`:

1. Use its active saved plan's calorie/protein/carbohydrate/fat targets. If there is no
   active plan, use the existing deterministic calculation from the current profile.
   No profile and no saved plan means targets are unavailable. A later profile edit
   does not rewrite saved plan targets. `target_sources` reports `saved_plan` and/or
   `current_profile`; profile fallback is not historical target reconstruction.
2. A day is scorable only when those four targets are finite/positive, its actual calories
   and macros are known, and it has an active plan with at least one logged planned item.
   Every consumed entry must have known calories/protein/carbohydrates/fat: compatible
   nutrient snapshots for meal logs, or the explicit stored macro columns for snacks,
   including macro-only custom snacks. Missing fiber, added sugar, or micronutrients do
   not disable these scores; unknown fiber and added sugar remain null in intake.
   Missing required macro snapshots and snack-only dates without verified
   planned-meal logging still cannot be scored.
3. Let `A(x,t) = max(0, 100 * (1 - abs(x-t)/t))`. This penalizes under- and over-target
   amounts symmetrically and stays in 0-100. Let `C_d = min(1, logged_plan_items / plan_items)`.
4. For each of calories/protein/carbs/fat, `S_k = sum(A(actual_d,k, target_d,k) * C_d) / N`,
   summing scorable days only; `N` is **all calendar days in the requested inclusive range**.
   Missing/unscorable dates contribute no alignment evidence, not a claim of zero actual
   intake. They remain in the denominator. If there are no scorable days, all scores are null.
5. `calorie_adherence.score = S_calories`.
   `macro_balance.score = (S_protein + S_carbs + S_fat) / 3`.
   `nutrition_score = (S_calories + macro_balance.score) / 2`.
   The three `*_adherence_percent` fields are the corresponding `S_k`, **not** an unbounded
   actual/target intake ratio. Round only final reported metrics to 2 decimals.

Coverage metadata distinguishes different kinds of missingness:

- `data_completeness.logged_days`: dates with any active meal log or standalone snack.
- `percentage = 100 * logged_days / days_in_range`: recorded-day coverage, NOT proof that
  all meals/nutrients are logged. `scored_days`/`unscored_days` expose eligibility.
- `planned_meals` counts active-plan items on recorded dates; `logged_planned_meals`
  counts distinct matching logged item IDs. `meal_logging_percentage` is their ratio
  times 100, or null if there are no such planned items.
- Calorie averages use recorded days with valid targets and known macros, including
  partial days. `calorie_adherence.logged_days` is this subset's count. Missing dates
  are not treated as zero intake in these averages.
- Unavailable reason: `no_recorded_nutrition`, `targets_unavailable`,
  `meal_logging_unverified`, or `nutrient_data_incomplete`.

For example, one perfectly aligned but only 1-of-4 logged-plan-items day in a two-day
range receives `100 * 1/4 / 2 = 12.5`, not a misleading 100. With complete logging but
calorie alignment 75 and macro alignments 100, 50, 50 in a one-day range, macro score
is 66.67 and overall nutrition score is 70.83 (rounding after the calculation).

The metric cannot verify off-app consumption, portion accuracy, product labels, or medical
appropriateness. It has no invented micronutrient or added-sugar target. No scores or
progress are persisted or generated by AI.

## Batch File Map

Latest verified results: nutrition scoring unit tests: `58 passed`; insight API tests:
`13 passed`; intake nutrient tests: `8 passed`. The final complete suite returned
`476 passed in 716.62s (0:11:56)` against
an isolated PostgreSQL database. The migration upgrade/downgrade/re-upgrade retained
12 foods, 41 recipes, and 656 recipe nutrient rows, and there is one Alembic head:
`20261028_0020`. Final compile checks passed; `git diff --check`: clean. No commit or push was made.

| Area | Created / Updated Files |
| --- | --- |
| Daily metrics | `app/models/daily_metrics.py`, `app/schemas/daily_metrics.py`, `app/services/daily_metrics_service.py`, `app/api/routes/daily_metrics.py` |
| Migration | `alembic/versions/20261028_0020_daily_metrics.py` |
| Registration/export | `app/models/__init__.py`, `app/api/router.py`, `app/services/account_service.py` |
| Structured nutrition | `app/nutrition/recipe.py`, `app/seed_data/foods.py`, `app/meal_planning/solver.py` |
| Daily intake | `app/schemas/nutrition.py`, `app/services/meal_log_service.py` |
| Insights | `app/nutrition/insights.py`, `app/services/insight_service.py`, `app/schemas/progress.py` |
| Tests | `tests/test_daily_metrics.py`, `tests/test_intake_nutrients.py`, `tests/test_nutrition_insight_scoring.py`, `tests/test_insights.py`, `tests/test_meal_logs.py` |
| Documentation | `README.md`, `TASKS.md`, `docs/API_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE_SCHEMA.md`, `docs/FRONTEND_API_GUIDE.md`, `docs/P0_CATALOG.md`, `docs/NUTRITION_TRACKING.md` |
