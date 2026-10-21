# Kcalm Planned REST API

## Implemented Progress and Account Extensions

The current implemented endpoint contract and exact frontend/Postman payloads for the
Priority 2/3 extensions are in [Frontend API Guide](FRONTEND_API_GUIDE.md).

All routes require bearer authentication:

| Methods | Routes |
| --- | --- |
| GET | `/api/v1/weight-logs` |
| PUT, DELETE | `/api/v1/weight-logs/{log_date}` |
| GET | `/api/v1/steps` |
| GET, PUT, DELETE | `/api/v1/steps/{log_date}` |
| GET, POST | `/api/v1/habits` |
| PATCH, DELETE | `/api/v1/habits/{habit_id}` |
| PUT | `/api/v1/habits/{habit_id}/completions/{log_date}` |
| GET | `/api/v1/habits/{habit_id}/history` |
| GET | `/api/v1/achievements`, `/api/v1/insights` |
| GET | `/api/v1/notifications` |
| POST | `/api/v1/notifications/sync` |
| PATCH | `/api/v1/notifications/{notification_id}/read` |
| POST | `/api/v1/auth/change-password` |
| DELETE | `/api/v1/users/me` |
| GET | `/api/v1/users/me/export` |
| GET | `/api/v1/integrations`, `/api/v1/integrations/{code}` |

Grocery detail responses add real completion counts. Recipe tags now support `pescatarian`
and `halal`; saved profile allergies filter only reviewed ingredient metadata. Unknown
allergens or missing reviews exclude candidates. Candidate preview adds scope/limitation
and unsupported-allergy metadata; it never certifies medical or cross-contact safety.

## API Principles

- REST endpoints are versioned under `/api/v1`.
- Requests and responses use JSON.
- Authentication is assumed to use bearer tokens, with implementation details to be finalized.
- Long-running or expensive operations return solver/import metadata when useful.
- Nutrition numbers in responses are calculated by backend services from structured data.
- OpenAI-derived content must be marked or traceable where it appears in explanations.

## Health and Metadata

### `GET /health`

Returns service health.

### `GET /api/v1/metadata/activity-levels`

Lists supported activity levels and multipliers.

### `GET /api/v1/metadata/goals`

Lists supported goals: fat loss, muscle gain, maintenance, recomposition.

### `GET /api/v1/metadata/dietary-restrictions`

Lists supported dietary restrictions and allergy tags.

### `GET /api/v1/metadata/equipment`

Lists supported kitchen equipment keys.

### `GET /api/v1/metadata/nutrients`

Lists tracked nutrients, units, and whether each is macro or micronutrient.

## Auth and Users

### `POST /api/v1/auth/register`

Creates a user account.

### `POST /api/v1/auth/login`

Authenticates a user and returns tokens.

Access and refresh tokens are implemented. `POST /api/v1/auth/refresh` exchanges a refresh
token for tokens. Password change/reset revokes older tokens through the user's token
version; clients sign in again. Separate logout/session management remains deferred.

### `GET /api/v1/auth/me`

Returns the current user.

### `DELETE /api/v1/users/me`

Requests account deletion.

## User Profile and Preferences

### `POST /api/v1/users/profile`

Creates the authenticated user's profile. Requires `Authorization: Bearer <token>`.

Request fields:

- `age`
- `sex`: `male`, `female`
- `height_cm`
- `weight_kg`
- `activity_level`: `sedentary`, `light`, `moderate`, `very_active`, `extra_active`
- `goal`: `fat_loss`, `muscle_gain`, `maintenance`, `recomposition`
- `target_rate`
- `max_cooking_minutes`
- `meals_per_day`
- `allergies`
- `dietary_restrictions`
- `preferred_foods`
- `disliked_foods`
- `equipment`

List fields are normalized by trimming whitespace, lowercasing, removing empty values, and deduplicating case-insensitively.

Returns `PROFILE_ALREADY_EXISTS` if a profile already exists.

### `GET /api/v1/users/profile`

Returns the current profile, preferences, restrictions, and equipment.

Requires `Authorization: Bearer <token>`.

Returns `PROFILE_NOT_FOUND` if the authenticated user has no profile.

### `PATCH /api/v1/users/profile`

Partially updates the authenticated user's profile. Requires `Authorization: Bearer <token>`.

PATCH behavior:

- Scalar fields included in the request are updated.
- Scalar fields omitted from the request are left unchanged.
- List fields included in the request replace the current list.
- List fields omitted from the request are left unchanged.
- An explicitly empty list removes all current values for that list.

### Deferred Profile Subresources

Separate restriction, preference, and equipment endpoints are deferred. They are currently managed through `POST /api/v1/users/profile` and `PATCH /api/v1/users/profile`.

### `POST /api/v1/profile/preferences/parse`

Uses OpenAI to parse natural-language preference text into structured, user-confirmable preferences.

## Nutrition Calculation

### `POST /api/v1/nutrition/calculate`

Calculates deterministic BMR, TDEE, target calories, and macro grams from supplied biometric inputs. Requires `Authorization: Bearer <token>`.

This endpoint does not read the stored user profile yet. It accepts calculation inputs directly so clients and Postman can verify the target calculation milestone independently.

Request fields:

- `age`
- `sex`: `male`, `female`
- `height_cm`
- `weight_kg`
- `activity_level`: `sedentary`, `light`, `moderate`, `very_active`, `extra_active`
- `goal`: `fat_loss`, `muscle_gain`, `maintenance`, `recomposition`
- `target_rate`: optional, greater than `0` and less than or equal to `2.5`

Validation reuses the current profile limits where practical:

- `age`: 13-120
- `height_cm`: 50-260
- `weight_kg`: 20-500

Formula:

- Male BMR: `10 * weight_kg + 6.25 * height_cm - 5 * age + 5`
- Female BMR: `10 * weight_kg + 6.25 * height_cm - 5 * age - 161`
- TDEE: `BMR * activity_multiplier`
- Target calories: goal-specific adjustment from TDEE.
- Protein: `weight_kg * protein_factor_for_goal`
- Fat: `weight_kg * 0.8`
- Carbs: remaining calories after protein and fat divided by `4`

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

If `target_rate` is omitted, fat loss uses `0.5` and muscle gain uses `0.25`. Maintenance and recomposition currently remain at TDEE even if `target_rate` is supplied.

Macro strategy:

- Protein uses total body weight because lean mass is not collected yet.
- Protein factors are `1.6 g/kg` for maintenance, `2.0 g/kg` for fat loss, `1.8 g/kg` for muscle gain, and `2.0 g/kg` for recomposition.
- Fat uses a `0.8 g/kg` floor.
- Carbs fill the remaining calories.

Kcal-per-gram constants:

- Protein: `4 kcal/g`
- Carbs: `4 kcal/g`
- Fat: `9 kcal/g`

Rounding:

- Internal calculations use unrounded floating-point values.
- API response values are rounded to one decimal place.

Example request:

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

Example response:

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

This endpoint intentionally does not return fiber or micronutrients. Those belong to later target calculation milestones.

### `GET /api/v1/nutrition/micronutrients`

Returns deterministic micronutrient targets for the authenticated user's saved profile. Requires `Authorization: Bearer <token>`.

This endpoint reads the current profile and uses the profile's `age` and `sex` to select centralized MVP reference data. It returns `PROFILE_NOT_FOUND` if the authenticated user has no saved profile.

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

- Reference values are centralized in `app/nutrition/micronutrients.py`.
- MVP values are based on National Academies Dietary Reference Intakes as surfaced through NIH Office of Dietary Supplements fact sheets, the National Academies sodium/potassium DRI report, and the National Academies fiber DRI summary.
- Age bands currently cover profile ages 13-120.
- Sex-specific rows use the existing `Sex` enum.
- The API does not assume more is always better: upper limits are nullable and included only where applicable.
- Sodium uses a Chronic Disease Risk Reduction Intake as its upper-limit-style value.
- Magnesium, vitamin A, and folate upper limits have scope notes because they apply to supplemental magnesium, preformed vitamin A, and synthetic folic acid respectively.

Response fields:

- `code`
- `name`
- `target`
- `unit`
- `minimum_target`
- `upper_limit`
- `upper_limit_unit`
- `target_type`
- `upper_limit_type`
- `age_min`
- `age_max`
- `sex`
- `source`
- `source_url`
- `source_version`
- `note`

Example response excerpt for a male user age 29:

```json
{
  "micronutrients": [
    {
      "code": "calcium",
      "name": "Calcium",
      "target": 1000,
      "unit": "mg",
      "minimum_target": 1000,
      "upper_limit": 2500,
      "upper_limit_unit": "mg",
      "target_type": "RDA",
      "upper_limit_type": "UL",
      "age_min": 19,
      "age_max": 50,
      "sex": "male",
      "source": "National Academies Dietary Reference Intakes via NIH ODS fact sheets",
      "source_url": "https://ods.od.nih.gov/factsheets/Calcium-HealthProfessional/",
      "source_version": "MVP DRI snapshot documented 2026-09-30",
      "note": null
    },
    {
      "code": "iron",
      "name": "Iron",
      "target": 8,
      "unit": "mg",
      "minimum_target": 8,
      "upper_limit": 45,
      "upper_limit_unit": "mg",
      "target_type": "RDA",
      "upper_limit_type": "UL",
      "age_min": 19,
      "age_max": 120,
      "sex": "male",
      "source": "National Academies Dietary Reference Intakes via NIH ODS fact sheets",
      "source_url": "https://ods.od.nih.gov/factsheets/Iron-HealthProfessional/",
      "source_version": "MVP DRI snapshot documented 2026-09-30",
      "note": null
    }
  ]
}
```

MVP limitations:

- Pregnancy and lactation-specific targets are not modeled.
- Micronutrient targets are not yet stored as versioned target snapshots.
- Meal planning and micronutrient plan validation are later milestones.

## Nutrition Targets

### `POST /api/v1/nutrition-targets/calculate`

Calculates proposed calorie, macro, and micronutrient targets from the current or supplied profile. Does not commit targets unless requested.

### `GET /api/v1/nutrition-targets/current`

Returns the active target set.

### `POST /api/v1/nutrition-targets/confirm`

Confirms calculated or user-edited targets and stores a versioned snapshot.

### `GET /api/v1/nutrition-targets/history`

Returns previous target versions.

### `PATCH /api/v1/nutrition-targets/current`

Updates user-editable targets while preserving audit metadata.

## Foods and Nutrition Data

### `GET /api/v1/foods`

Lists internal structured foods. Requires `Authorization: Bearer <token>`.

Query parameters:

- `search`: optional name search.
- `category`: optional exact category filter, case-insensitive.
- `limit`: optional, default `20`, min `1`, max `100`.
- `offset`: optional, default `0`.

List responses intentionally return only food summary data, not every nutrient and serving row.

Example:

```http
GET /api/v1/foods?search=chicken
```

Example response:

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

### `GET /api/v1/foods/{food_id}`

Returns one food with metadata, nutrient values normalized per 100g, and serving options. Requires `Authorization: Bearer <token>`.

Example response:

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
    },
    {
      "code": "protein",
      "name": "Protein",
      "amount": 31,
      "unit": "g"
    }
  ],
  "servings": [
    {
      "name": "100 g",
      "grams": 100
    },
    {
      "name": "1 piece",
      "grams": 120
    }
  ]
}
```

Returns `FOOD_NOT_FOUND` for unknown IDs.

Food database notes:

- Nutrients are stored as rows, not fixed columns, so new nutrient codes can be added later.
- Nutrient values are normalized per 100 grams.
- Serving rows store gram conversions only and do not duplicate nutrition values.
- Development seed values are labeled as internal fixtures and are not production USDA data.

### `GET /api/v1/foods/usda/search`

Searches USDA FoodData Central. Requires `Authorization: Bearer <token>` and a configured `USDA_API_KEY`.

Query parameters:

- `q`: required search text, 1-128 characters.
- `page_size`: optional, default `10`, min `1`, max `50`.
- `page`: optional, default `1`, min `1`.

Search returns a Kcalm-shaped response and does not persist results automatically.

Example:

```http
GET /api/v1/foods/usda/search?q=chicken&page_size=10&page=1
```

Example response:

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

Controlled errors:

- `USDA_API_KEY_MISSING`
- `USDA_TIMEOUT`
- `USDA_NETWORK_ERROR`
- `USDA_AUTH_ERROR`
- `USDA_RATE_LIMITED`
- `USDA_UPSTREAM_ERROR`
- `USDA_MALFORMED_RESPONSE`

### `POST /api/v1/foods/usda/import/{fdc_id}`

Imports one USDA FoodData Central food into the local `foods`, `food_nutrients`, and `food_servings` tables. Requires `Authorization: Bearer <token>` and a configured `USDA_API_KEY`.

Import flow:

1. Fetch food details from USDA by FDC ID.
2. Parse the USDA response.
3. Map supported USDA nutrients to Kcalm nutrient codes.
4. Normalize nutrient values into Kcalm's per-100g model.
5. Persist `Food`, `FoodNutrient`, and `FoodServing` rows transactionally.
6. Return the local food detail response.

Duplicate behavior:

- USDA food identity is `source = usda` and `source_food_id = <fdc_id>`.
- If the food already exists locally, the endpoint returns `200 OK` with `status = existing`.
- New imports return `201 Created` with `status = imported`.

Example response:

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
      },
      {
        "code": "protein",
        "name": "Protein",
        "amount": 31,
        "unit": "g"
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

Nutrient mapping:

- Canonical USDA nutrient mapping lives in `app/integrations/usda_nutrients.py`.
- Supported imported nutrient codes are `calories`, `protein`, `carbohydrates`, `fat`, `fiber`, `calcium`, `iron`, `magnesium`, `potassium`, `sodium`, `vitamin_a`, `vitamin_c`, `vitamin_d`, `vitamin_b12`, and `folate`.
- Deterministic conversion supports compatible `kcal`, `g`, `mg`, and `mcg` units.
- Unsupported units are skipped rather than guessed.

Per-100g normalization:

- Imported nutrient rows use USDA `foodNutrients` amounts as the per-100g source.
- Serving-based `labelNutrients` are not imported because they are not the canonical per-100g source.
- Household servings are imported only when USDA provides a reliable `gramWeight`.
- A `100 g` serving is added consistently.

Controlled errors:

- `USDA_API_KEY_MISSING`
- `USDA_TIMEOUT`
- `USDA_NETWORK_ERROR`
- `USDA_AUTH_ERROR`
- `USDA_FOOD_NOT_FOUND`
- `USDA_RATE_LIMITED`
- `USDA_UPSTREAM_ERROR`
- `USDA_MALFORMED_RESPONSE`
- `USDA_NO_SUPPORTED_NUTRIENTS`
- `FOOD_IMPORT_FAILED`

### `POST /api/v1/admin/foods/import/usda`

Deferred. Future admin or bulk USDA import endpoint. Current MVP imports are available through `POST /api/v1/foods/usda/import/{fdc_id}`.

### `GET /api/v1/admin/foods/imports`

Deferred. Admin endpoint to list food data import batches.

### `GET /api/v1/units`

Lists supported units and conversion metadata.

## Recipes

### `GET /api/v1/recipes`

Lists active structured recipes. Requires `Authorization: Bearer <token>`.

Query parameters:

- `search`: optional name search.
- `tag`: optional exact tag filter using a supported recipe tag.
- `max_total_time_minutes`: optional upper bound for derived total time.
- `limit`: optional, default `20`, min `1`, max `100`.
- `offset`: optional, default `0`.

Example:

```http
GET /api/v1/recipes?tag=quick&max_total_time_minutes=20
```

Example response:

```json
{
  "items": [
    {
      "id": "00000000-0000-0000-0000-000000000000",
      "name": "Chicken Rice Bowl",
      "description": "Simple high-protein bowl.",
      "servings": 2,
      "total_time_minutes": 15,
      "difficulty": "easy",
      "active": true,
      "tags": ["high_protein", "lunch", "quick"]
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### `POST /api/v1/recipes/candidates/preview`

Returns deterministic solver-preparation candidates for the authenticated user's saved profile. Requires `Authorization: Bearer <token>`.

This endpoint does not run OR-Tools, create meal plans, rank recipes, persist solver state, or call OpenAI. It filters existing structured recipes and returns eligible candidates, rejected recipes with structured first rejection reasons, exclusion summary counts, and soft preference metadata.

Request fields:

- `meal_type`: optional; one of `breakfast`, `lunch`, `dinner`, or `snack`.
- `max_total_time_minutes`: optional request override. When omitted, the profile's `max_cooking_minutes` is used.
- `require_complete_nutrition`: default `false`. When `true`, recipes with incomplete required nutrients are excluded.
- `required_nutrient_codes`: optional list of supported recipe nutrient codes. Only used by strict completeness filtering. When empty and strict completeness is enabled, all supported recipe nutrients are required.
- `excluded_recipe_ids`: optional recipe UUIDs to exclude explicitly.
- `required_tags`: optional supported recipe tags that every candidate must contain.
- `excluded_tags`: optional supported recipe tags that candidates must not contain.

Example request:

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

Example response:

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

Filter order:

1. Active recipes.
2. Explicit recipe exclusions.
3. Meal type tags.
4. Required and excluded tags.
5. Total time.
6. Equipment.
7. Dietary restrictions.
8. Allergies.
9. Disliked foods.
10. Nutrition completeness.

Hard constraints:

- Archived recipes are excluded.
- Meal type filtering uses explicit recipe tags.
- Time filtering uses request `max_total_time_minutes` first, then profile `max_cooking_minutes`.
- Required recipe equipment must be available in the user's profile.
- Dietary restrictions map to explicit tags: `vegetarian`, `vegan`, `dairy_free`, `gluten_free`, `pescatarian`, or `halal`.
- `required_tags`, `excluded_tags`, and `excluded_recipe_ids` are hard filters.
- Disliked foods are handled with exact normalized food-name matches against recipe ingredients.
- Nutrition completeness is deterministic from persisted `recipe_nutrients`.

Soft preference metadata:

- `preference_match_count`
- `matched_preference_food_names`
- `matched_preference_tags`

Soft preferences do not rank or exclude candidates in this milestone.

Allergy support uses reviewed ingredient-food metadata. Missing reviews and unsupported
profile allergy codes exclude candidates. `allergy_filtering_supported` reports whether
the profile's codes are supported; cross-contact and medical safety remain unassessed.
Metadata is never inferred from names or text. See the frontend guide for review procedures.

Candidate rejection reason codes:

- `inactive`
- `explicitly_excluded`
- `wrong_meal_type`
- `missing_required_tag`
- `excluded_tag`
- `exceeds_time_limit`
- `missing_required_equipment`
- `dietary_restriction_mismatch`
- `allergy_conflict`
- `allergy_metadata_missing`
- `unsupported_allergy`
- `disliked_food`
- `incomplete_nutrition`

Controlled errors:

- `INVALID_TOKEN`
- `PROFILE_NOT_FOUND`
- `INVALID_CANDIDATE_MEAL_TYPE`
- `INVALID_CANDIDATE_TAG`
- `INVALID_REQUIRED_NUTRIENT`

### `GET /api/v1/recipes/{recipe_id}`

Returns recipe metadata, ingredients, steps, tags, required equipment, total recipe nutrition, and per-serving nutrition. Requires `Authorization: Bearer <token>`.

Nutrition values are calculated from local `Food` and `FoodNutrient` rows, then persisted in `recipe_nutrients`. They are not accepted from client input.

Example response excerpt:

```json
{
  "id": "00000000-0000-0000-0000-000000000000",
  "name": "Chicken Rice Bowl",
  "description": "Simple high-protein bowl.",
  "servings": 2,
  "prep_time_minutes": 5,
  "cook_time_minutes": 10,
  "total_time_minutes": 15,
  "difficulty": "easy",
  "instructions_summary": "Combine ingredients.",
  "active": true,
  "tags": ["high_protein", "lunch", "quick"],
  "equipment": ["stovetop"],
  "ingredients": [
    {
      "id": "00000000-0000-0000-0000-000000000000",
      "food_id": "00000000-0000-0000-0000-000000000000",
      "food_name": "Chicken Breast",
      "quantity_grams": 100,
      "display_quantity": "100",
      "display_unit": "g",
      "preparation_note": "cooked",
      "position": 1
    }
  ],
  "steps": [
    {
      "id": "00000000-0000-0000-0000-000000000000",
      "position": 1,
      "instruction": "Warm the chicken.",
      "phase": "cook",
      "duration_seconds": 120,
      "timer": true,
      "timer_required": true,
      "timer_seconds": 120,
      "cue_action": null,
      "animation_key": null,
      "media_asset_key": null,
      "visual_cue": null
    }
  ],
  "nutrition": {
    "total": [
      {
        "code": "calories",
        "name": "Calories",
        "amount": 295,
        "unit": "kcal",
        "complete": true,
        "missing_ingredient_count": 0
      }
    ],
    "per_serving": [
      {
        "code": "calories",
        "name": "Calories",
        "amount": 147.5,
        "unit": "kcal",
        "complete": true,
        "missing_ingredient_count": 0
      }
    ]
  }
}
```

Returns `RECIPE_NOT_FOUND` for unknown or archived recipes.

### `POST /api/v1/recipes`

Creates a structured recipe using existing local Food IDs. Requires `Authorization: Bearer <token>`.

Request behavior:

- `total_time_minutes` is derived as `prep_time_minutes + cook_time_minutes`.
- `ingredients` must contain at least one item.
- Every ingredient must reference an existing `foods.id`.
- `quantity_grams` must be greater than zero.
- Step positions must be unique when provided.
- Tags and equipment must be supported structured keys.
- If `quick` is present in tags, total time must be 20 minutes or less.
- Recipe nutrition is calculated transactionally from FoodNutrient rows.

Example request:

```json
{
  "name": "Chicken Rice Bowl",
  "description": "Simple high-protein bowl.",
  "servings": 2,
  "prep_time_minutes": 5,
  "cook_time_minutes": 10,
  "difficulty": "easy",
  "instructions_summary": "Combine ingredients.",
  "ingredients": [
    {
      "food_id": "00000000-0000-0000-0000-000000000000",
      "quantity_grams": 100,
      "display_quantity": "100",
      "display_unit": "g",
      "preparation_note": "cooked",
      "position": 1
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
    }
  ],
  "tags": ["lunch", "quick", "high_protein"],
  "equipment": ["stovetop"]
}
```

### `PATCH /api/v1/recipes/{recipe_id}`

Partially updates a recipe. Requires `Authorization: Bearer <token>`.

PATCH behavior:

- Scalar fields included in the request are updated.
- Omitted scalar fields remain unchanged.
- Included `ingredients`, `steps`, `tags`, or `equipment` replace that full collection.
- Omitted collections remain unchanged.
- Nutrition is recalculated transactionally after each successful update.

### `DELETE /api/v1/recipes/{recipe_id}`

Archives a recipe by setting `active = false`. Requires `Authorization: Bearer <token>`.

Archived recipes are hidden from list and detail endpoints. The behavior is intentionally soft-delete because future meal plans may reference recipe IDs.

### Recipe Nutrition Calculation

Formula:

```text
ingredient nutrient = food nutrient per 100g * quantity_grams / 100
recipe total = sum ingredient nutrients
per-serving = recipe total / recipe.servings
```

Supported nutrient codes are the current Kcalm food nutrient codes:

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

Missing nutrient policy:

- Known values are summed.
- If a food lacks a nutrient row, that recipe nutrient remains calculated from known ingredients and is marked `complete = false`.
- `missing_ingredient_count` reports how many ingredients lacked that nutrient.
- Missing values are not fabricated.

Supported tags:

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

Supported recipe equipment:

- `oven`
- `stovetop`
- `microwave`
- `blender`
- `air_fryer`

Controlled errors:

- `RECIPE_NOT_FOUND`
- `INVALID_RECIPE_FOOD`
- `RECIPE_REQUIRES_INGREDIENTS`
- `DUPLICATE_RECIPE_INGREDIENT_POSITION`
- `DUPLICATE_RECIPE_STEP_POSITION`
- `INVALID_RECIPE_TAG`
- `INVALID_RECIPE_EQUIPMENT`
- `QUICK_RECIPE_TOO_LONG`
- `RECIPE_NUTRIENT_UNIT_MISMATCH`
- `RECIPE_SAVE_FAILED`

### `POST /api/v1/admin/recipes`

Deferred. Recipe creation is currently available through authenticated `POST /api/v1/recipes`.

### `PATCH /api/v1/admin/recipes/{recipe_id}`

Deferred. Recipe updates are currently available through authenticated `PATCH /api/v1/recipes/{recipe_id}`.

### `POST /api/v1/admin/recipes/{recipe_id}/validate`

Deferred. Recipe nutrition recalculation currently runs automatically during create/update.

## Recipe Execution

Recipe execution endpoints expose deterministic step-by-step cooking data for mobile clients. They require `Authorization: Bearer <token>`. The backend snapshots recipe instructions, serving context, timer metadata, equipment summary, and ingredient summary when a session starts. Later recipe edits do not change already-started sessions.

Execution does not call OpenAI, generate animations, run server-side countdown workers, mutate meal plans, or log meals as eaten.

### `POST /api/v1/recipes/{recipe_id}/execution-sessions`

Starts an execution session directly from an active recipe.

Request:

```json
{
  "servings": 1.0
}
```

Behavior:

- Verifies the recipe exists and is active.
- Requires `servings > 0`.
- Requires at least one structured recipe step.
- Creates one `recipe_execution_sessions` row.
- Snapshots ordered recipe steps into `recipe_execution_step_snapshots`.
- Returns the session with ordered step snapshots.

Controlled errors:

- `INVALID_TOKEN`
- `RECIPE_NOT_FOUND`
- `RECIPE_EXECUTION_STEPS_MISSING`
- `RECIPE_EXECUTION_SAVE_FAILED`

### `POST /api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/execution-session`

Starts an execution session from a persisted meal-plan item.

Behavior:

- Verifies meal-plan ownership with non-leaking `MEAL_PLAN_NOT_FOUND` behavior.
- Verifies the item belongs to that plan.
- Rejects archived plans with `MEAL_PLAN_ARCHIVED`.
- Uses the meal-plan item's recipe name snapshot and servings.
- Uses meal-plan item ingredient snapshots where available.
- Reads current structured recipe steps at execution start, then snapshots them.
- Prevents more than one active session for the same meal-plan item with `EXECUTION_SESSION_ALREADY_ACTIVE`.
- Completed and abandoned historical sessions do not block a new session.

Controlled errors:

- `INVALID_TOKEN`
- `MEAL_PLAN_NOT_FOUND`
- `MEAL_PLAN_ITEM_NOT_FOUND`
- `MEAL_PLAN_ARCHIVED`
- `RECIPE_NOT_FOUND`
- `RECIPE_EXECUTION_STEPS_MISSING`
- `EXECUTION_SESSION_ALREADY_ACTIVE`
- `RECIPE_EXECUTION_SAVE_FAILED`

### `GET /api/v1/recipe-execution-sessions/{session_id}`

Returns a user-owned execution session. Other users receive `RECIPE_EXECUTION_SESSION_NOT_FOUND`.

Response fields:

- `session_id`
- `recipe_id`
- `meal_plan_id`
- `meal_plan_item_id`
- `recipe_name`
- `servings`
- `status`: `not_started`, `in_progress`, `completed`, or `abandoned`
- `current_step_index`
- `total_estimated_time_minutes`
- `required_equipment`
- `ingredients`
- `step_count`
- `progress`
- `steps`
- `started_at`
- `completed_at`
- `created_at`
- `updated_at`

Step fields:

- `step_index`
- `recipe_step_position`
- `instruction`
- `phase`: `prep`, `cook`, `rest`, `assemble`, or `serve`
- `duration_seconds`
- `timer_required`
- `timer_seconds`
- `completed`
- `completed_at`
- `equipment`
- `ingredients`
- `cue_action`
- `animation_key`
- `media_asset_key`
- `visual_cue`
- `timer_started_at`
- `timer_completed_at`

Example response excerpt:

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "recipe_id": "00000000-0000-0000-0000-000000000001",
  "meal_plan_id": null,
  "meal_plan_item_id": null,
  "recipe_name": "Chicken Rice Bowl",
  "servings": 1.0,
  "status": "in_progress",
  "current_step_index": 0,
  "total_estimated_time_minutes": 15,
  "required_equipment": ["stovetop"],
  "ingredients": [
    {
      "ingredient_id": "00000000-0000-0000-0000-000000000002",
      "food_id": "00000000-0000-0000-0000-000000000003",
      "food_name": "Chicken Breast",
      "quantity_grams": 120.0,
      "display_quantity": "1",
      "display_unit": "piece",
      "preparation_note": "cooked"
    }
  ],
  "step_count": 2,
  "progress": {
    "completed_steps": 0,
    "total_steps": 2,
    "percent_complete": 0.0
  },
  "steps": [
    {
      "step_index": 0,
      "recipe_step_position": 1,
      "instruction": "Warm olive oil in a pan over medium heat.",
      "phase": "cook",
      "duration_seconds": 60,
      "timer_required": true,
      "timer_seconds": null,
      "completed": false,
      "equipment": [],
      "ingredients": [],
      "animation_key": null,
      "media_asset_key": null,
      "visual_cue": null
    }
  ]
}
```

### `PATCH /api/v1/recipe-execution-sessions/{session_id}/progress`

Updates the current step pointer for a resumable `in_progress` session.

Request:

```json
{
  "current_step_index": 1
}
```

Validation:

- `current_step_index` must be inside the session's step range.
- Completed sessions return `EXECUTION_SESSION_COMPLETED`.
- Abandoned sessions return `EXECUTION_SESSION_ABANDONED`.

### `POST /api/v1/recipe-execution-sessions/{session_id}/steps/{step_index}/complete`

Marks one execution step snapshot complete and records `completed_at`. This does not alter the original recipe.

### `POST /api/v1/recipe-execution-sessions/{session_id}/complete`

Marks the session completed, sets `completed_at`, moves progress to the final step, and marks all step snapshots complete. It does not create a meal log automatically.

### `POST /api/v1/recipe-execution-sessions/{session_id}/abandon`

Marks the session abandoned and preserves the historical snapshot.

Limitations:

- Step-level ingredient/equipment mapping is not modeled yet; per-step arrays are empty unless future structured mappings are added.
- Meal-plan-item starts snapshot current recipe steps at execution start because meal plans do not yet store recipe step snapshots.
- Timer fields are metadata only; the client owns countdown display.
- Animation keys and media keys are placeholders only.

## Meal Planning

### `POST /api/v1/meal-plans/solve/preview`

Runs the one-day OR-Tools solver preview without persisting a meal plan. Requires `Authorization: Bearer <token>`.

Processing flow:

```text
User Profile + Targets
        ->
Recipe Candidate Filtering
        ->
Eligible Candidate DTOs
        ->
OR-Tools Solver
        ->
Non-persisted Daily Plan Result
```

This endpoint calculates the authenticated user's current calorie, macro, and micronutrient targets from the saved profile. Persisted target sets are not implemented yet. It then calls the existing recipe candidate filtering service and passes only eligible candidate DTOs to the solver.

The solver does not query recipes directly, does not call USDA, does not call OpenAI, and does not write `meal_plans` or meal history rows.

Request fields:

- `meal_slots`: optional list of slot objects. When omitted, the default is required breakfast, lunch, dinner, and optional snack.
- `meal_slots[].meal_type`: `breakfast`, `lunch`, `dinner`, or `snack`.
- `meal_slots[].required`: boolean. Required slots must receive exactly one recipe. Optional slots receive zero or one recipe.
- `max_total_time_minutes`: optional candidate-filter override.
- `require_complete_nutrition`: default `true`; forwarded to candidate filtering.
- `required_nutrient_codes`: optional strict completeness nutrient subset.
- `excluded_recipe_ids`: optional recipe UUIDs to exclude before solving.
- `required_tags`: optional candidate-filter required recipe tags.
- `excluded_tags`: optional candidate-filter excluded recipe tags.
- `solver_time_limit_seconds`: optional CP-SAT limit, greater than `0` and at most `5`; defaults to `3`.

Example request:

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

Example response excerpt:

```json
{
  "status": "optimal",
  "meals": [
    {
      "meal_type": "breakfast",
      "recipe_id": "00000000-0000-0000-0000-000000000000",
      "recipe_name": "Greek Yogurt Oat Bowl",
      "serving_amount": 1.0,
      "nutrition": {
        "calories": 300.0,
        "protein": 25.0,
        "carbohydrates": 40.0,
        "fat": 5.0,
        "fiber": 6.0,
        "calcium": 250.0
      }
    }
  ],
  "daily_totals": {
    "calories": 1900.0,
    "protein": 150.0,
    "carbohydrates": 210.0,
    "fat": 60.0
  },
  "targets": {
    "calories": 2278.375,
    "protein_g": 164.0,
    "carbohydrates_g": 258.09375,
    "fat_g": 65.60000000000001,
    "micronutrients": [
      {
        "code": "calcium",
        "name": "Calcium",
        "target": 1000.0,
        "unit": "mg",
        "minimum_target": 1000.0,
        "upper_limit": 2500.0,
        "upper_limit_type": "UL"
      }
    ]
  },
  "deviations": [
    {
      "nutrient_code": "calories",
      "nutrient_name": "Calories",
      "target": 2278.375,
      "actual": 1900.0,
      "unit": "kcal",
      "deviation_amount": -378.375,
      "deviation_percent": -16.607,
      "tolerance_lower": 2164.456,
      "tolerance_upper": 2392.294,
      "status": "below_tolerance"
    }
  ],
  "micronutrient_coverage": [
    {
      "nutrient_code": "calcium",
      "nutrient_name": "Calcium",
      "target": 1000.0,
      "actual": 920.0,
      "unit": "mg",
      "coverage_percent": 92.0,
      "met": false,
      "upper_limit": 2500.0,
      "upper_limit_type": "UL",
      "upper_limit_applicable": true,
      "upper_limit_exceeded": false
    }
  ],
  "within_preferred_tolerance": false,
  "objective_value": 123456,
  "infeasibility_reasons": [],
  "solve_time_seconds": 0.02,
  "candidate_count": 8
}
```

Solver rules:

- Meal type assignment is based on candidate `meal_tags`, which originate from explicit recipe tags.
- Default required slots are breakfast, lunch, and dinner.
- Snack is optional by default.
- Each selected meal uses `1.0` recipe serving.
- The same recipe cannot fill multiple meal slots in the same day.
- Nutrition values come from candidate per-serving `RecipeNutrient` values.
- Calories and macros use +/- 5% preferred tolerance.
- Nutrition precision is optimized through objective penalties rather than hard nutrition feasibility bands.

Integer scaling:

- CP-SAT receives integer nutrient values only.
- Nutrients stay in their current internal units.
- Values are scaled by `1000` and rounded half-up.

Objective:

- Minimize normalized calorie deviation.
- Minimize normalized protein, carbohydrate, and fat deviation.
- Minimize micronutrient shortfall.
- Penalize applicable upper-limit excess for `UL` and `CDRR` targets.
- Apply deterministic tie-breaking by option order.

Status values:

- `optimal`: CP-SAT proved the best result within the time limit.
- `feasible`: CP-SAT found a result but did not prove optimality before the time limit.
- `infeasible`: no controlled structural assignment or solver result is available.

Controlled infeasible reasons include:

- `no_eligible_candidates`
- `all_candidate_nutrition_malformed`
- `missing_meal_slot_candidate:<meal_type>`
- `solver_no_structurally_valid_assignment`

Controlled errors:

- `INVALID_TOKEN`
- `PROFILE_NOT_FOUND`
- `MEAL_SOLVER_INVALID_INPUT`
- `NUTRITION_TARGETS_INVALID`
- `MICRONUTRIENT_TARGETS_UNSUPPORTED`
- `MICRONUTRIENT_REFERENCE_DATA_MISSING`
- Candidate filtering validation errors such as `INVALID_CANDIDATE_TAG`.

### `POST /api/v1/meal-plans`

Generates and persists one daily meal plan for the authenticated user. Requires `Authorization: Bearer <token>`.

Processing flow:

```text
User Profile
    -> Nutrition Targets
    -> Recipe Candidate Filtering
    -> OR-Tools Constraint Solver
    -> Nutrition Validation Metadata
    -> Transactional Snapshot Persistence
    -> API Response
```

This endpoint reuses the same solver orchestration as `POST /api/v1/meal-plans/solve/preview`. It does not bypass candidate filtering, duplicate solver logic, call OpenAI, or calculate nutrition from recipe text.

Request fields are the same as solver preview plus:

- `plan_date`: optional ISO date. Defaults to the current UTC date when omitted.

Example request:

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

Example response excerpt:

```json
{
  "meal_plan_id": "00000000-0000-0000-0000-000000000000",
  "plan_date": "2026-10-03",
  "status": "generated",
  "solver_status": "optimal",
  "meals": [
    {
      "id": "00000000-0000-0000-0000-000000000001",
      "meal_type": "breakfast",
      "recipe_id": "00000000-0000-0000-0000-000000000002",
      "recipe_name": "Greek Yogurt Oat Bowl",
      "servings": 1.0,
      "position": 1,
      "nutrition": {
        "calories": 300.0,
        "protein": 25.0
      }
    }
  ],
  "daily_totals": {
    "calories": 1900.0,
    "protein": 150.0,
    "carbohydrates": 210.0,
    "fat": 60.0
  },
  "targets": {
    "calories": 2278.375,
    "protein_g": 164.0,
    "carbohydrates_g": 257.99375,
    "fat_g": 65.60000000000001,
    "micronutrients": []
  },
  "deviations": [],
  "micronutrient_coverage": [],
  "within_preferred_tolerance": false,
  "objective_value": 123456,
  "solve_time_seconds": 0.02,
  "candidate_count": 8,
  "created_at": "2026-10-03T00:00:00Z",
  "updated_at": "2026-10-03T00:00:00Z"
}
```

Persistence behavior:

- Only solver results with `optimal` or `feasible` status are persisted.
- `infeasible` results return `MEAL_PLAN_INFEASIBLE` and do not create plan rows.
- One active `generated` plan is allowed per user per `plan_date`.
- Duplicate generated plans return `PLAN_ALREADY_EXISTS` with HTTP `409`.
- `DELETE` changes status to `archived` instead of physically deleting the plan.
- Archived plans are excluded from the default list but can be requested with `status=archived`.

Snapshot behavior:

- Recipe names, selected meal types, serving amounts, and item nutrient contributions are stored on meal-plan rows.
- Macro targets and micronutrient target metadata are stored with the plan.
- Detail and list nutrition totals are reconstructed from persisted item nutrient snapshots.
- Saved plans remain stable if the source recipe or profile changes later.

Controlled errors:

- `INVALID_TOKEN`
- `PROFILE_NOT_FOUND`
- `MEAL_PLAN_INFEASIBLE`
- `PLAN_ALREADY_EXISTS`
- `MEAL_PLAN_SAVE_FAILED`
- Candidate filtering validation errors such as `INVALID_CANDIDATE_TAG`.

### `GET /api/v1/meal-plans`

Lists persisted meal plans for the authenticated user. Requires `Authorization: Bearer <token>`.

Query parameters:

- `plan_date`: optional ISO date.
- `status`: optional, `generated` or `archived`. Defaults to `generated` when omitted.

Example:

```http
GET /api/v1/meal-plans?plan_date=2026-10-03
```

Example response:

```json
{
  "items": [
    {
      "meal_plan_id": "00000000-0000-0000-0000-000000000000",
      "plan_date": "2026-10-03",
      "status": "generated",
      "solver_status": "optimal",
      "daily_totals": {
        "calories": 1900.0,
        "protein": 150.0
      },
      "within_preferred_tolerance": false,
      "created_at": "2026-10-03T00:00:00Z",
      "updated_at": "2026-10-03T00:00:00Z"
    }
  ],
  "total": 1
}
```

### `GET /api/v1/meal-plans/{meal_plan_id}`

Returns a persisted meal plan owned by the authenticated user. Requires `Authorization: Bearer <token>`.

The response shape matches `POST /api/v1/meal-plans`.

Returns `MEAL_PLAN_NOT_FOUND` when the plan does not exist or belongs to another user.

### `POST /api/v1/meal-plans/{meal_plan_id}/confirm`

Deferred. Current plan statuses are `generated` and `archived`.

### `DELETE /api/v1/meal-plans/{meal_plan_id}`

Soft-archives a persisted meal plan owned by the authenticated user. Requires `Authorization: Bearer <token>`.

Returns `204 No Content` on success. The plan remains available from detail and from list requests that include `status=archived`.

### `POST /api/v1/meal-plans/{meal_plan_id}/regenerate`

Deferred. Full-day regeneration is not implemented in the single-meal swap milestone.

## Weekly Meal Plans

### `POST /api/v1/weekly-meal-plans`

Creates one persisted weekly meal plan for the authenticated user. Requires `Authorization: Bearer <token>`.

Processing flow:

```text
User Profile
    -> Nutrition Targets
    -> Recipe Candidate Filtering
    -> Existing Daily OR-Tools Solver
    -> Persisted Daily Meal Plans
    -> WeeklyMealPlan container
    -> Meal item ingredient snapshots
```

This endpoint does not implement a separate weekly optimizer. It derives `end_date` as `start_date + 6 days`, then creates exactly seven daily meal plans through the same daily solver and persistence path used by `POST /api/v1/meal-plans`.

Request fields are the same as daily solver preview plus:

- `start_date`: required ISO date.

Example request:

```json
{
  "start_date": "2026-10-12",
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

Example response excerpt:

```json
{
  "weekly_plan_id": "00000000-0000-0000-0000-000000000000",
  "start_date": "2026-10-12",
  "end_date": "2026-10-18",
  "status": "generated",
  "daily_plans": [
    {
      "meal_plan_id": "00000000-0000-0000-0000-000000000001",
      "plan_date": "2026-10-12",
      "status": "generated",
      "meals": []
    }
  ],
  "created_at": "2026-10-12T00:00:00Z",
  "updated_at": "2026-10-12T00:00:00Z"
}
```

Creation behavior:

- Weekly creation is fully atomic. If any day fails, the week and all newly generated daily plans are rolled back.
- Duplicate active weekly plans for the same user and date range return `WEEKLY_PLAN_ALREADY_EXISTS`.
- Existing active generated daily plans inside the requested date range return `DAILY_PLAN_ALREADY_EXISTS_FOR_WEEK`.
- The weekly orchestrator attempts to exclude the previous day's selected recipe IDs when generating the next day.
- If adjacent-day variety exclusions make a day infeasible, the day is retried without the variety exclusion.

Controlled errors:

- `INVALID_TOKEN`
- `PROFILE_NOT_FOUND`
- `WEEKLY_PLAN_ALREADY_EXISTS`
- `DAILY_PLAN_ALREADY_EXISTS_FOR_WEEK`
- `WEEKLY_PLAN_INFEASIBLE`
- `WEEKLY_PLAN_SAVE_FAILED`
- Daily solver and candidate filtering errors such as `INVALID_CANDIDATE_TAG`.

### `GET /api/v1/weekly-meal-plans`

Lists persisted weekly plans owned by the authenticated user. Requires `Authorization: Bearer <token>`.

Query parameters:

- `status`: optional, `generated` or `archived`. Defaults to `generated` when omitted.

Example response:

```json
{
  "items": [
    {
      "weekly_plan_id": "00000000-0000-0000-0000-000000000000",
      "start_date": "2026-10-12",
      "end_date": "2026-10-18",
      "status": "generated",
      "daily_plan_count": 7,
      "created_at": "2026-10-12T00:00:00Z",
      "updated_at": "2026-10-12T00:00:00Z"
    }
  ],
  "total": 1
}
```

### `GET /api/v1/weekly-meal-plans/{weekly_plan_id}`

Returns a persisted weekly plan with its seven daily plan responses. Requires `Authorization: Bearer <token>`.

Returns `WEEKLY_PLAN_NOT_FOUND` when the plan does not exist or belongs to another user.

### `DELETE /api/v1/weekly-meal-plans/{weekly_plan_id}`

Soft-archives a weekly plan owned by the authenticated user. Requires `Authorization: Bearer <token>`.

Returns `204 No Content` on success. The weekly plan and its generated member daily plans are marked `archived`; unrelated standalone daily plans are not touched.

### `GET /api/v1/weekly-meal-plans/{weekly_plan_id}/grocery/preview`

Returns deterministic grocery ingredient aggregation for a weekly plan. Requires `Authorization: Bearer <token>`.

Aggregation source:

```text
meal_plan_item_ingredients.quantity_grams
```

Snapshot quantity is written during daily plan persistence using:

```text
recipe_ingredient.quantity_grams * meal_plan_item.servings
```

Aggregation identity is stable `food_id`, not display name. Output is sorted deterministically by food name and ID.

Example response:

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

Historical behavior:

- Grocery previews use persisted ingredient snapshots, not live recipe ingredients.
- Recipe edits after weekly plan creation do not change existing grocery previews.
- Plans without item ingredient snapshots return `GROCERY_SNAPSHOT_MISSING`.

Controlled errors:

- `INVALID_TOKEN`
- `WEEKLY_PLAN_NOT_FOUND`
- `GROCERY_SNAPSHOT_MISSING`

Persisted grocery-list workflows are available through `POST /api/v1/weekly-meal-plans/{weekly_plan_id}/grocery-list` and the `/api/v1/grocery-lists` endpoints. The preview endpoint remains non-persistent.

### `POST /api/v1/weekly-meal-plans/{weekly_plan_id}/grocery-list`

Creates a persisted grocery list from the weekly plan's saved `meal_plan_item_ingredients` snapshots. Requires `Authorization: Bearer <token>`.

Behavior:

- Verifies weekly plan ownership with non-leaking `WEEKLY_PLAN_NOT_FOUND` behavior.
- Rejects archived weekly plans with `WEEKLY_PLAN_ARCHIVED`.
- Rejects a second active list for the same weekly plan with `GROCERY_LIST_ALREADY_EXISTS`.
- Aggregates automatic items by stable `food_id`.
- Writes generated item quantities in grams with `unit: "g"` and `quantity_grams`.
- Stores `food_name_snapshot` on each list item for historical stability.
- Commits list and items transactionally.

Response status: `201 Created`.

Example response:

```json
{
  "grocery_list_id": "00000000-0000-0000-0000-000000000100",
  "weekly_plan_id": "00000000-0000-0000-0000-000000000000",
  "status": "active",
  "generated_at": "2026-10-08T12:00:00Z",
  "items": [
    {
      "id": "00000000-0000-0000-0000-000000000101",
      "food_id": "00000000-0000-0000-0000-000000000001",
      "food_name": "Chicken Breast",
      "quantity": 350.0,
      "unit": "g",
      "quantity_grams": 350.0,
      "category": "meat_seafood",
      "checked": false,
      "manually_added": false,
      "created_at": "2026-10-08T12:00:00Z",
      "updated_at": "2026-10-08T12:00:00Z"
    }
  ],
  "created_at": "2026-10-08T12:00:00Z",
  "updated_at": "2026-10-08T12:00:00Z"
}
```

Controlled errors:

- `INVALID_TOKEN`
- `WEEKLY_PLAN_NOT_FOUND`
- `WEEKLY_PLAN_ARCHIVED`
- `GROCERY_SNAPSHOT_MISSING`
- `GROCERY_LIST_ALREADY_EXISTS`
- `GROCERY_LIST_SAVE_FAILED`

## Meal Swapping

### `POST /api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/swap-options`

Deferred. The current milestone applies one best replacement directly through the swap endpoint instead of returning ranked options.

### `POST /api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/swap`

Replaces one meal-plan item in a persisted generated daily plan. Requires `Authorization: Bearer <token>`.

Processing flow:

```text
Persisted Meal Plan
    -> locked meal item snapshots
    -> candidate filtering for the selected meal type
    -> excluded current and locked recipe IDs
    -> existing OR-Tools solver with locked nutrition as base totals
    -> transactional item snapshot update
    -> updated persisted plan response
```

Default behavior:

- The selected item is replaceable.
- Every other item in the plan is locked.
- The replacement must match the selected item's `meal_type`.
- The current recipe is excluded.
- Locked meal recipe IDs are excluded to prevent duplicate recipe reuse.
- Plan target snapshots are preserved; current profile target changes are not used.
- Locked meal nutrition comes from saved `meal_plan_item_nutrients`.
- The selected item's recipe ID, recipe name snapshot, serving amount, and nutrient snapshots are updated in place.

Request fields:

- `max_total_time_minutes`: optional candidate-filter override.
- `require_complete_nutrition`: optional, defaults to `true`.
- `required_tags`: optional candidate-filter required recipe tags.
- `excluded_tags`: optional candidate-filter excluded recipe tags.
- `excluded_recipe_ids`: optional recipe UUIDs to exclude in addition to the current and locked recipe IDs.
- `solver_time_limit_seconds`: optional CP-SAT limit, greater than `0` and at most `5`; defaults to `3`.
- `different_protein`: optional boolean, currently unsupported when `true`.
- `eating_out`: optional boolean, currently unsupported when `true`.

Example request:

```json
{
  "max_total_time_minutes": 20,
  "required_tags": ["quick"],
  "excluded_tags": [],
  "excluded_recipe_ids": []
}
```

An unconstrained swap can send:

```json
{}
```

Response:

- Same shape as `GET /api/v1/meal-plans/{meal_plan_id}`.
- `daily_totals`, `deviations`, and `micronutrient_coverage` are recalculated from saved item snapshots.
- `targets` remain the original plan target snapshots.

Controlled errors:

- `INVALID_TOKEN`
- `MEAL_PLAN_NOT_FOUND`
- `MEAL_PLAN_ITEM_NOT_FOUND`
- `MEAL_PLAN_ARCHIVED`
- `NO_SWAP_CANDIDATE`
- `UNSUPPORTED_SWAP_CONSTRAINT`
- `MEAL_SWAP_SAVE_FAILED`
- Candidate filtering validation errors such as `INVALID_CANDIDATE_TAG`.

Unsupported/deferred:

- `different_protein` is deferred because recipes do not yet have reliable structured protein-source metadata.
- `eating_out` is deferred because restaurant/external meal records are not modeled yet.
- Full-day regeneration is deferred.

### `POST /api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/ai-swap`

Interprets a natural-language swap request, validates the structured constraints, and then delegates to the existing deterministic swap service. Requires `Authorization: Bearer <token>`.

The AI layer does not select the recipe. The selected item's current meal type is preserved by the swap service, the current and locked recipes are excluded, candidate filtering runs, and OR-Tools chooses the replacement.

Request:

```json
{
  "text": "Give me something quicker and dairy free"
}
```

Response:

- Same shape as `GET /api/v1/meal-plans/{meal_plan_id}`.

Controlled AI errors:

- `AI_INPUT_TOO_LONG`
- `AI_TIMEOUT`
- `AI_RATE_LIMITED`
- `AI_AUTHENTICATION_FAILED`
- `AI_CONFIGURATION_ERROR`
- `AI_SERVICE_UNAVAILABLE`
- `AI_MALFORMED_RESPONSE`
- `AI_CONSTRAINT_VALIDATION_FAILED`
- `AI_CLARIFICATION_REQUIRED`
- `AI_UNSUPPORTED_CONSTRAINT`

Controlled deterministic swap errors still apply, including `NO_SWAP_CANDIDATE`, `MEAL_PLAN_NOT_FOUND`, `MEAL_PLAN_ITEM_NOT_FOUND`, and `MEAL_PLAN_ARCHIVED`.

## Logging and Adaptation

### `POST /api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/log`

Creates or updates the current actual intake log for one persisted meal-plan item. Requires `Authorization: Bearer <token>`.

The endpoint is an idempotent upsert for the current active log. Re-logging the same item updates the existing `meal_logs` row and replaces its `meal_log_nutrients` snapshots transactionally.

Ate as planned request:

```json
{
  "type": "ate_as_planned"
}
```

Behavior:

- Copies the persisted `meal_plan_item_nutrients` rows exactly.
- Does not read live recipe rows.
- Does not modify planned meal snapshots.

Corrected food request:

```json
{
  "type": "corrected",
  "source_type": "food",
  "food_id": "00000000-0000-0000-0000-000000000001",
  "quantity_grams": 180
}
```

Food correction nutrition source:

```text
food_nutrient.amount per 100g * quantity_grams / 100
```

Corrected recipe request:

```json
{
  "type": "corrected",
  "source_type": "recipe",
  "recipe_id": "00000000-0000-0000-0000-000000000002",
  "servings": 1.5
}
```

Recipe correction nutrition source:

```text
recipe_nutrients.per_serving_amount * servings
```

Example response:

```json
{
  "meal_log_id": "00000000-0000-0000-0000-000000000010",
  "meal_plan_id": "00000000-0000-0000-0000-000000000020",
  "meal_plan_item_id": "00000000-0000-0000-0000-000000000030",
  "log_date": "2026-10-12",
  "type": "ate_as_planned",
  "status": "active",
  "source_type": null,
  "food_id": null,
  "recipe_id": null,
  "quantity_grams": null,
  "servings": null,
  "nutrient_complete": true,
  "nutrients": [
    {
      "code": "calories",
      "name": "Calories",
      "amount": 550.0,
      "unit": "kcal"
    }
  ],
  "known_nutrient_codes": ["calories"],
  "missing_nutrient_codes": [],
  "created_at": "2026-10-09T12:00:00Z",
  "updated_at": "2026-10-09T12:00:00Z"
}
```

Controlled errors:

- `INVALID_TOKEN`
- `MEAL_PLAN_NOT_FOUND`
- `MEAL_PLAN_ITEM_NOT_FOUND`
- `MEAL_PLAN_ARCHIVED`
- `FOOD_NOT_FOUND`
- `RECIPE_NOT_FOUND`
- `MEAL_LOG_SAVE_FAILED`

### `DELETE /api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/log`

Deletes the current active log for one meal-plan item. Requires `Authorization: Bearer <token>`.

Returns `204 No Content` on success. Planned snapshots are unchanged. If no current log exists, returns `MEAL_LOG_NOT_FOUND`.

### `GET /api/v1/meal-plans/{meal_plan_id}/actual-summary`

Returns deterministic planned-vs-actual nutrition data for one persisted meal plan. Requires `Authorization: Bearer <token>`.

Actual totals rule:

- Logged items contribute their `meal_log_nutrients` snapshots.
- Unlogged items do not count as consumed.
- No live recipe, food import, USDA, or OpenAI call is made.

Example response:

```json
{
  "meal_plan_id": "00000000-0000-0000-0000-000000000020",
  "plan_date": "2026-10-12",
  "planned_totals": {
    "calories": 2200.0,
    "protein": 160.0
  },
  "actual_totals": {
    "calories": 550.0,
    "protein": 40.0
  },
  "targets": {
    "calories": 2200.0,
    "protein_g": 160.0,
    "carbohydrates_g": 240.0,
    "fat_g": 70.0,
    "micronutrients": []
  },
  "difference_actual_vs_planned": {
    "calories": -1650.0,
    "protein": -120.0
  },
  "difference_actual_vs_target": {
    "calories": -1650.0,
    "protein": -120.0
  },
  "actual_known_nutrient_codes": ["calories", "protein"],
  "missing_actual_target_nutrient_codes": [],
  "adherence": {
    "planned_meals_count": 3,
    "logged_meals_count": 1,
    "unlogged_meals_count": 2,
    "ate_as_planned_count": 1,
    "corrected_count": 0,
    "adherence_percent": 33.333333
  }
}
```

Adherence rule:

```text
adherence_percent = ate_as_planned_count / planned_meals_count * 100
```

Missing nutrient behavior:

- Known nutrients are preserved as snapshots.
- Missing food nutrient rows are not invented.
- Summary metadata identifies target nutrients that are missing from actual logged totals.

### `POST /api/v1/meal-plans/{source_plan_id}/adaptive-preview`

Returns a deterministic adaptive next-day preview for a logged source meal plan. Requires `Authorization: Bearer <token>`.

The endpoint does not persist a new meal plan. It uses the source plan's saved calorie, macro, and micronutrient target snapshots plus actual intake logs. It never accepts client-provided nutrition totals as authoritative.

Request body is optional and matches the daily solver preview constraint body:

```json
{
  "meal_slots": [
    {"meal_type": "breakfast", "required": true},
    {"meal_type": "lunch", "required": true},
    {"meal_type": "dinner", "required": true}
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

If `meal_slots` is omitted, the service uses the source plan's persisted meal types in item-position order. The next-day date is `source_plan.plan_date + 1 day`.

Example response:

```json
{
  "source_plan_id": "00000000-0000-0000-0000-000000000020",
  "next_day_date": "2026-10-13",
  "actual_totals": {
    "calories": 2500.0,
    "protein": 150.0
  },
  "target_totals": {
    "calories": 2200.0,
    "protein": 160.0
  },
  "deviation": {
    "calories": 300.0,
    "protein": -10.0
  },
  "micronutrient_deviation": {
    "calcium": -200.0
  },
  "policy": {
    "policy_version": "adaptive_v1",
    "compensation_fraction": 0.25,
    "max_adjustment_kcal": 250.0,
    "max_adjustment_percent": 0.1,
    "minimum_adjusted_calories": 1200.0
  },
  "adjusted_targets": {
    "source_plan_id": "00000000-0000-0000-0000-000000000020",
    "base_calorie_target": 2200.0,
    "previous_day_actual_calories": 2500.0,
    "previous_day_calorie_deviation": 300.0,
    "compensation_fraction": 0.25,
    "raw_compensation_amount": -75.0,
    "compensation_amount": -75.0,
    "adjusted_calorie_target": 2125.0,
    "base_macro_targets": {
      "protein": 160.0,
      "carbohydrates": 240.0,
      "fat": 70.0
    },
    "adjusted_macro_targets": {
      "protein": 160.0,
      "carbohydrates": 221.25,
      "fat": 70.0
    },
    "micronutrient_strategy": "report_only_standard_targets_unchanged",
    "safety_caps_applied": [],
    "policy_version": "adaptive_v1"
  },
  "solver_preview": {
    "status": "feasible",
    "meals": [],
    "daily_totals": {},
    "targets": {
      "calories": 2125.0,
      "protein_g": 160.0,
      "carbohydrates_g": 221.25,
      "fat_g": 70.0,
      "micronutrients": []
    },
    "deviations": [],
    "micronutrient_coverage": [],
    "within_preferred_tolerance": false,
    "objective_value": 0,
    "infeasibility_reasons": [],
    "solve_time_seconds": 0.0,
    "candidate_count": 0
  }
}
```

Controlled errors:

- `MEAL_PLAN_NOT_FOUND`
- `MEAL_PLAN_ARCHIVED`
- `INCOMPLETE_DAILY_LOG`
- `ACTUAL_LOG_NUTRITION_INCOMPLETE`
- `ADAPTIVE_TARGET_INVALID`
- `MEAL_SOLVER_INVALID_INPUT`

### `POST /api/v1/meal-plans/{source_plan_id}/generate-next-day`

Creates a persisted adaptive next-day meal plan. Requires `Authorization: Bearer <token>`.

The service computes the same adaptive target DTO as preview, then reuses existing recipe candidate filtering, the existing OR-Tools daily solver, and the existing daily meal-plan persistence path. It also saves a `meal_plan_adaptations` snapshot row with policy and target metadata.

Returns `201 Created`.

Response shape:

```json
{
  "source_plan_id": "00000000-0000-0000-0000-000000000020",
  "adaptation": {
    "policy_version": "adaptive_v1",
    "base_calorie_target": 2200.0,
    "compensation_amount": -75.0,
    "adjusted_calorie_target": 2125.0
  },
  "plan": {
    "meal_plan_id": "00000000-0000-0000-0000-000000000021",
    "plan_date": "2026-10-13",
    "status": "generated",
    "solver_status": "feasible"
  }
}
```

Conflict and transaction behavior:

- Existing active generated next-day plan returns `PLAN_ALREADY_EXISTS`; the service does not overwrite or merge plans.
- Infeasible adaptive solver output returns `ADAPTIVE_PLAN_INFEASIBLE`.
- If adaptation metadata or meal item persistence fails, the new plan is rolled back.
- The source plan and source logs are never mutated.

## Grocery Lists

### `GET /api/v1/grocery-lists`

Lists grocery lists owned by the authenticated user. Requires `Authorization: Bearer <token>`.

Query parameters:

- `weekly_plan_id`: optional UUID filter.
- `status`: optional, one of `active` or `archived`; defaults to `active`.

Example response:

```json
{
  "items": [
    {
      "grocery_list_id": "00000000-0000-0000-0000-000000000100",
      "weekly_plan_id": "00000000-0000-0000-0000-000000000000",
      "status": "active",
      "item_count": 12,
      "checked_item_count": 2,
      "generated_at": "2026-10-08T12:00:00Z",
      "created_at": "2026-10-08T12:00:00Z",
      "updated_at": "2026-10-08T12:00:00Z"
    }
  ],
  "total": 1
}
```

### `GET /api/v1/grocery-lists/{grocery_list_id}`

Returns full grocery list details and items. Users can only read their own lists; other users receive `GROCERY_LIST_NOT_FOUND`.

### `PATCH /api/v1/grocery-lists/{grocery_list_id}/items/{item_id}`

Updates checked state, quantity, unit, or category for one item. Requires list ownership and an active list.

Request fields:

- `checked`: optional boolean.
- `quantity`: optional positive number.
- `unit`: optional non-blank string.
- `category`: optional grocery category: `produce`, `meat_seafood`, `dairy`, `grains`, `pantry`, `frozen`, or `other`.

At least one field is required. If `quantity` or `unit` changes, `quantity_grams` is recalculated only for gram units (`g`, `gram`, `grams`); otherwise it becomes `null`.

Example request:

```json
{
  "checked": true
}
```

### `POST /api/v1/grocery-lists/{grocery_list_id}/items`

Adds a manual grocery item. Requires list ownership and an active list.

Response status: `201 Created`.

Request:

```json
{
  "name": "Sparkling Water",
  "quantity": 2,
  "unit": "bottle",
  "category": "other"
}
```

Manual items have `food_id: null`, `manually_added: true`, and keep the supplied unit. `quantity_grams` is populated only when the unit is grams.

### `DELETE /api/v1/grocery-lists/{grocery_list_id}/items/{item_id}`

Permanently removes an item from an active grocery list owned by the authenticated user. Returns `204 No Content`.

### `POST /api/v1/grocery-lists/{grocery_list_id}/regenerate`

Rebuilds automatic grocery items from the weekly plan's current persisted meal item ingredient snapshots. Requires list ownership and an active list.

Regeneration behavior:

- Deletes and recreates automatic items from snapshots.
- Preserves manual items.
- Preserves automatic checked state by Food ID.
- Resets generated item quantities and categories to deterministic snapshot-derived values.
- Does not regenerate meal plans.
- Does not read live recipe ingredient rows.

### `DELETE /api/v1/grocery-lists/{grocery_list_id}`

Soft-archives a grocery list owned by the authenticated user. Returns `204 No Content`.

Archived lists:

- Are hidden from the default `GET /api/v1/grocery-lists` response.
- Are visible with `?status=archived`.
- Cannot be modified or regenerated.

Controlled errors:

- `INVALID_TOKEN`
- `GROCERY_LIST_NOT_FOUND`
- `GROCERY_LIST_ITEM_NOT_FOUND`
- `GROCERY_LIST_ARCHIVED`
- `GROCERY_LIST_SAVE_FAILED`

Category strategy:

- Known Food categories are mapped deterministically to grocery categories.
- Unknown categories return `other`.
- Store-specific aisle grouping and retailer integrations are deferred.

## AI Features

AI endpoints require `Authorization: Bearer <token>`. They do not calculate nutrition, create recipes, choose final meals directly, or persist plans unless they call an existing validated deterministic service such as meal swap.

### `POST /api/v1/ai/constraints/interpret`

Parses natural-language meal planning text into validated structured constraints. The response contains no nutrition numbers and no AI-supplied IDs.

Request:

```json
{
  "text": "I want a quick high protein dinner with no chicken",
  "context_meal_type": null
}
```

Response:

```json
{
  "requested_action": "find_options",
  "meal_type": "dinner",
  "max_total_time_minutes": null,
  "required_tags": ["quick", "high_protein"],
  "excluded_tags": [],
  "excluded_recipe_ids": ["00000000-0000-0000-0000-000000000111"],
  "avoid_food_names": ["chicken"],
  "preference_food_names": [],
  "unsupported_constraints": [],
  "clarification_required": false,
  "clarification_question": null,
  "confidence": 0.87,
  "resolved_avoid_foods": [
    {
      "phrase": "chicken",
      "food_id": "00000000-0000-0000-0000-000000000001",
      "food_name": "Chicken Breast",
      "excluded_recipe_ids": ["00000000-0000-0000-0000-000000000111"]
    }
  ]
}
```

Validation behavior:

- Text length is limited to `500` normalized characters.
- Canonical tags are limited to `quick`, `vegetarian`, `vegan`, `dairy_free`, `gluten_free`, and `high_protein`.
- Food avoidance names are resolved through local `foods` rows before recipe exclusions are produced.
- Unknown AI-generated tags, arbitrary IDs, or malformed structured output return controlled errors.
- Allergy-like and medical-diet requests are reported as unsupported constraints.

### `POST /api/v1/ai/meal-options`

Interprets natural language, validates constraints, and calls existing recipe candidate filtering. It does not call OR-Tools and does not rank nutrition fit with AI.

Request:

```json
{
  "text": "Give me a vegetarian lunch under 15 minutes"
}
```

Response:

```json
{
  "interpretation": {
    "meal_type": "lunch",
    "max_total_time_minutes": 15,
    "required_tags": ["vegetarian"],
    "excluded_recipe_ids": []
  },
  "candidate_preview": {
    "candidates": [],
    "total_eligible": 0,
    "exclusion_summary": {},
    "excluded": [],
    "allergy_filtering_supported": true,
    "unsupported_dietary_restrictions": [],
    "filter_order": []
  }
}
```

If clarification is required or constraints are unsupported, `candidate_preview` is `null` and the structured interpretation explains what is missing or unsupported.

### Deferred AI explanation endpoints

The following are intentionally deferred:

- `POST /api/v1/ai/explain-targets`
- `POST /api/v1/ai/explain-meal-plan`
- `POST /api/v1/ai/explain-swap`

## Solver Diagnostics

### `GET /api/v1/solver-runs/{solver_run_id}`

Returns solver inputs summary, objective values, validation status, and infeasibility reasons where available.

### `GET /api/v1/meal-plans/{meal_plan_id}/validation`

Returns nutrition target comparison for calories, macros, and tracked micronutrients.

## Postman Support

### OpenAPI Source

FastAPI serves the OpenAPI document at `/openapi.json` and interactive Swagger UI at `/docs`.
There is no custom `/api/v1/postman/openapi.json` route in the MVP backend.

### MVP Manual Checklist

Run the Postman smoke flow in this order with `base_url = http://127.0.0.1:8000/api/v1`:

1. Register and login: `POST /auth/register`, `POST /auth/login`; expect `201` then `200` and save `access_token`.
2. Profile: `POST /users/profile`, `PATCH /users/profile`; expect `201` then `200`.
3. Nutrition targets: `POST /nutrition/calculate`, `GET /nutrition/micronutrients`; expect deterministic BMR/TDEE/macros and DRI micronutrients.
4. Recipes and foods: `GET /foods`, optional `GET /foods/usda/search`, optional `POST /foods/usda/import/{fdc_id}`, `GET /recipes`.
5. Candidate preview: `POST /recipes/candidates/preview`; verify candidates, rejected recipes, summary counts, unsupported allergy codes, and ingredient-metadata-only scope.
6. Daily plan: `POST /meal-plans`, then `GET /meal-plans/{meal_plan_id}`; verify saved targets, item nutrients, totals, deviations, and micronutrient coverage.
7. Swap: `POST /meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/swap`; verify locked meals and target snapshots are preserved.
8. Weekly plan: `POST /weekly-meal-plans`; verify seven persisted daily plans.
9. Grocery list: `GET /weekly-meal-plans/{weekly_plan_id}/grocery/preview`, `POST /weekly-meal-plans/{weekly_plan_id}/grocery-list`, `PATCH /grocery-lists/{grocery_list_id}/items/{item_id}`, `POST /grocery-lists/{grocery_list_id}/items`, `DELETE /grocery-lists/{grocery_list_id}/items/{item_id}`.
10. Meal logging: `POST /meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/log` with `ate_as_planned`, then with `corrected` food data.
11. Actual summary: `GET /meal-plans/{meal_plan_id}/actual-summary`; verify planned-vs-actual totals and adherence.
12. Adaptive planning: `POST /meal-plans/{meal_plan_id}/adaptive-preview`, then `POST /meal-plans/{meal_plan_id}/generate-next-day`; expect `200` then `201` after all meals are logged.
13. AI constraints: `POST /ai/constraints/interpret`, `POST /ai/meal-options`, and `POST /meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/ai-swap`; verify AI only returns/uses structured constraints.
14. Recipe execution: `POST /meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/execution-session`, `PATCH /recipe-execution-sessions/{session_id}/progress`, `POST /recipe-execution-sessions/{session_id}/complete`.

### Planned Collection Folders

- Health.
- Auth.
- Profile.
- Nutrition Targets.
- Foods.
- Recipes.
- Recipe Execution.
- Meal Plans.
- Meal Swaps.
- Logging.
- Grocery Lists.
- AI.
- Solver Diagnostics.
- Admin Imports.
