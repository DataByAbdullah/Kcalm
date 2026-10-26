# Kcalm AI Architecture

## Boundary Rule

Achievements and progress/nutrition insights are now deterministic read services and do
not call OpenAI. Structured profile allergies can filter reviewed food allergen metadata
through candidate filtering, but natural-language allergy/medical safety intent remains
unsupported. AI cannot populate food allergen reviews or certify safety. The integration
capability catalog reports configuration status without claiming verified connectivity.

OpenAI is a language interface, not a nutrition source.

LLMs must never provide the calories, macros, micronutrients, serving sizes, reference targets, recipe nutrition totals, daily totals, or validation status used by Kcalm. Those values come only from structured food data, reference tables, and deterministic backend calculations.

## Approved OpenAI Uses

### Natural-Language Meal Request Parsing

Input examples:

- "Make dinner quick and no dairy."
- "Swap lunch for something with chicken."
- "I am eating out tonight."

OpenAI may extract:

- Meal slot.
- Time constraint.
- Ingredient preference.
- Dietary exclusion.
- Cuisine preference.
- Eating-out intent.
- Need for a swap or regeneration.

Output must be structured and validated with Pydantic. It must not include nutrition numbers.

### Preference Extraction

OpenAI may turn free text into proposed user preferences:

- Likes and dislikes.
- Preferred proteins.
- Cuisine preferences.
- Texture or spice preferences.
- Cooking effort preferences.

Extracted preferences are proposals. The backend stores them as weighted tags only after validation and, where appropriate, user confirmation.

### Constraint Extraction

OpenAI may parse constraints from text:

- "No dairy."
- "No peanuts."
- "I only have a microwave."
- "Under 15 minutes."
- "Vegetarian this week."

All extracted constraints are mapped to canonical backend keys. Allergy-like constraints should be treated conservatively and confirmed.

### Explanations From Calculated Data

OpenAI may explain already-calculated data:

- Why a target set was calculated.
- Why a meal plan fits the target.
- Why a swap is valid.
- How logged deviations affect tomorrow's plan.

The model receives the calculated values as input and may only explain them. It must not recalculate or replace them.

### Recipe Step Wording

OpenAI may help rewrite structured cooking steps into clearer prose if:

- Ingredients are unchanged.
- Quantities are unchanged.
- Timers are unchanged.
- Animation component keys are unchanged.
- Nutrition values are unchanged.

## Prohibited OpenAI Uses

OpenAI must not:

- Generate nutrition facts.
- Estimate calories or macros from a food name.
- Estimate micronutrients.
- Choose final meal plans without OR-Tools and validation.
- Create solver-eligible recipes from free-form text without structured food mapping and nutrition calculation.
- Modify user targets.
- Decide whether a meal plan passes validation.
- Decide whether a recipe meets a micronutrient target.
- Infer recipe execution timers, step phases, ingredient references, or animation metadata for the current execution backend.
- Write directly to foods, food nutrients, recipe ingredients, recipe nutrition snapshots, target sets, or meal plan nutrition totals.

## AI Service Design

All OpenAI calls go through a dedicated AI service.

Responsibilities:

- Build prompts from versioned templates.
- Call the OpenAI Python SDK.
- Request structured output when possible.
- Validate outputs with Pydantic v2.
- Normalize parsed values to canonical backend enums and IDs.
- Reject outputs that contain forbidden nutrition fields.
- Log AI interaction metadata with redacted inputs.

No router, solver, nutrition engine, or repository should call OpenAI directly.

Current implementation:

- `app/integrations/openai_client.py` owns the OpenAI Python SDK call.
- `app/services/ai_constraint_service.py` owns deterministic validation, canonical mapping, food avoidance resolution, and downstream service orchestration.
- `app/schemas/ai.py` defines request, LLM output, and API response schemas.
- `OPENAI_API_KEY` and `OPENAI_MODEL` are configured through settings.
- Default model is `gpt-5-mini`; deployments may override this with `OPENAI_MODEL`.
- `OPENAI_TIMEOUT_SECONDS` controls the SDK request timeout.
- Structured output token budget is capped in `app/integrations/openai_client.py` by `MAX_CONSTRAINT_OUTPUT_TOKENS`.

The AI integration is lazy-loaded and mockable. Automated tests inject a fake interpreter and never call the real OpenAI API.

## Structured Constraint Contract

The LLM may return only `NaturalLanguageMealConstraintLLMOutput`:

- `requested_action`: `find_options`, `swap_meal`, or `unknown`.
- `meal_type`: `breakfast`, `lunch`, `pre_workout`, `dinner`, or `snack`.
- `max_total_time_minutes`.
- `required_tags`.
- `excluded_tags`.
- `avoid_food_names`.
- `preference_food_names`.
- `unsupported_constraints`.
- `clarification_required`.
- `clarification_question`.
- `confidence`.

The schema forbids extra fields. AI-supplied IDs such as `recipe_id`, `food_id`, or `meal_plan_id` are invalid.

Canonical supported tags:

- `quick`
- `vegetarian`
- `vegan`
- `dairy_free`
- `gluten_free`
- `high_protein`

Central synonym mapping lives in `app/services/ai_constraint_service.py`, for example:

- `fast`, `faster`, `speedy` -> `quick`
- `veggie` -> `vegetarian`
- `plant based` -> `vegan`
- `no dairy` -> `dairy_free`
- `protein heavy` -> `high_protein`

Unsupported constraints are preserved as metadata rather than forced into backend filters:

- `different_protein`
- `restaurant`
- `low_fodmap`
- `keto`
- allergy-like requests
- unsupported medical diets

## Food Avoidance Resolution

The LLM may extract phrases such as `chicken`, `salmon`, or `oats`, but it may not supply IDs.

Resolution flow:

1. Normalize the phrase.
2. Search local `foods`.
3. Accept one exact normalized match, or one whole-token match.
4. Return `AI_CONSTRAINT_VALIDATION_FAILED` for unresolved or ambiguous phrases.
5. Convert resolved Food IDs into recipe exclusions through `recipe_ingredients`.

This keeps exclusions deterministic and prevents dangerous fuzzy matching.

## Endpoint Flow

### Interpret

`POST /api/v1/ai/constraints/interpret`

Returns validated structured constraints only. It does not select recipes or mutate plans.

### Meal Options

`POST /api/v1/ai/meal-options`

Flow:

1. Interpret natural language.
2. Validate tags, time, meal type, unsupported constraints, and food avoidance.
3. Call existing recipe candidate filtering.
4. Return candidate preview metadata.

This endpoint does not call OR-Tools.

### AI Swap

`POST /api/v1/meal-plans/{meal_plan_id}/items/{meal_plan_item_id}/ai-swap`

Flow:

1. Load the owned meal plan and item.
2. Interpret natural language with the item's meal type as context.
3. Reject clarification-required or unsupported constraints.
4. Build a normal `MealSwapRequest`.
5. Call the existing swap service.
6. Existing candidate filtering and OR-Tools choose the replacement.
7. Existing swap transaction persists the result or rolls back.

AI never directly chooses the replacement recipe.

## Error Handling

OpenAI SDK and validation failures are mapped to controlled API errors:

- `AI_INPUT_TOO_LONG`
- `AI_TIMEOUT`
- `AI_RATE_LIMITED`
- `AI_AUTHENTICATION_FAILED`
- `AI_CONFIGURATION_ERROR`
- `AI_SERVICE_UNAVAILABLE`
- `AI_EMPTY_RESPONSE`
- `AI_MALFORMED_RESPONSE`
- `AI_CONSTRAINT_VALIDATION_FAILED`
- `AI_CLARIFICATION_REQUIRED`
- `AI_UNSUPPORTED_CONSTRAINT`

Raw SDK exceptions are not exposed.

## Input and Privacy Controls

- Natural-language input is limited to 500 normalized characters.
- Prompts are concise and task-specific.
- The service does not send the full food database, full recipe catalog, or meal-plan history.
- Logs include operation, model, latency, and category metadata only.
- API keys and bearer tokens are never logged.

## Current Persistence Decision

This milestone is stateless. It adds no database migration and does not persist prompts or responses. `ai_interactions` remains deferred until there is a concrete audit/history product requirement.

## Final MVP AI Hardening Notes

The final backend MVP keeps AI on the safe side of the boundary:

- The OpenAI SDK path uses `responses.parse()` with Pydantic structured output.
- `output_parsed=None` is classified by response status/content: incomplete, refusal, malformed structured output, or genuinely empty output.
- Ambiguous wording such as "lighter" requires clarification instead of inventing calorie or portion constraints.
- Allergy and medical/safety intent is normalized to unsupported constraints; it is not treated as ordinary food avoidance and the API does not claim allergen-safe meals.
- Deterministic post-processing catches clear safety intent even if the model places a food phrase in `avoid_food_names`.
- Unknown tags, fake IDs, malformed schemas, unresolved food avoidance, and unsupported AI swap constraints return controlled API errors.
- Automated tests mock AI calls and do not require live OpenAI access.

## Data Flow: Meal Request Parsing

1. API receives natural-language request.
2. AI service sends prompt with allowed schema.
3. OpenAI returns structured constraints.
4. Pydantic validates the response.
5. Constraint normalizer maps values to canonical tags.
6. Candidate filtering uses the normalized constraints.
7. OR-Tools solves the plan or swap.
8. Nutrition engine validates the result.
9. API returns calculated nutrition and optional explanation.

## Data Flow: Explanation

1. Backend calculates targets, plan totals, deltas, and validation status.
2. AI service receives only the already-calculated facts and safe metadata.
3. OpenAI produces user-facing explanation text.
4. Backend returns the explanation alongside deterministic values.

If the explanation contradicts calculated values or invents nutrition facts, it must be rejected or regenerated.

## Guardrails

### Schema Guardrails

AI output schemas must exclude fields for:

- Calories.
- Protein.
- Carbohydrates.
- Fat.
- Fiber.
- Micronutrient values.
- Serving grams.
- RDA or DRI values.
- Validation status.

### Prompt Guardrails

Prompts must explicitly say:

- Do not estimate nutrition.
- Return only allowed structured fields.
- Unknown values should be `null` or omitted.
- Use canonical labels where supplied.

### Runtime Guardrails

The AI service must:

- Reject unknown fields.
- Reject numeric nutrition-like fields.
- Reject free-form recipe ingredients as solver-ready nutrition data.
- Record validation failures.
- Fall back to manual constraint selection if parsing fails.

### Test Guardrails

Tests must prove:

- AI-provided nutrition fields are ignored or rejected.
- A meal plan cannot be returned without deterministic validation.
- Explanations cannot mutate response nutrition values.
- Failed AI parsing does not block manual meal generation.

## Auditing

Each AI interaction should store:

- User ID where applicable.
- Interaction type.
- Model.
- Prompt version.
- Input hash.
- Redacted input.
- Validated output.
- Status.
- Error reason if rejected.

Prompt and schema versions are important because parsed constraints can affect meal generation.

## Privacy

Only send the minimum data needed for the AI task.

Avoid sending:

- Full profile history.
- Full meal log history.
- Raw medical notes.
- Unneeded identifiers.

Prefer summarized, redacted, and task-specific inputs.
