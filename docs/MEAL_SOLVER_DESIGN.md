# Kcalm Meal Solver Design

## P0 Four-Slot Compatibility

Explicit slots support `breakfast`, `lunch`, `pre_workout`, and `dinner`, all required,
using the existing candidate-to-slot assignment and nutrition validation. `pre_workout`
is a distinct recipe tag, not a renamed snack. Omitting slots preserves existing
breakfast/lunch/dinner and optional snack defaults. No objective, nutrition tolerance,
or safety relaxation was introduced for the expanded catalog. Explicit swap `recipe_id`
selection narrows only already-eligible candidates before invoking the same solver.
See [P0 Catalog](P0_CATALOG.md) for reviewed fixture scope and exact eligible counts.

## Purpose

The meal solver creates meal plans and swaps that satisfy nutrition targets and user constraints using verified recipe candidates. It never accepts LLM-generated nutrition numbers.

Required flow:

User Profile -> Nutrition Targets -> Recipe Candidate Filtering -> Constraint Solver -> Nutrition Validation -> API Response

## Final MVP Solver Status

The MVP solver path is implemented and validated for daily previews, persisted daily plans, single-meal swaps, weekly orchestration, and adaptive next-day generation. It uses deterministic candidate filtering before OR-Tools and never accepts nutrition numbers from OpenAI or free text.

Current implementation choices:

- Candidate order is stable before solving.
- OR-Tools CP-SAT uses fixed `1.0` serving portions for MVP.
- The solver uses a fixed seed, single worker, and request-bounded timeout.
- Meal slots, recipe reuse, explicit exclusions, candidate eligibility, and locked-meal nutrition are enforced structurally.
- Calories, macros, micronutrient shortfall, and applicable upper-limit excess are optimized as objective penalties and reported with tolerance metadata.
- Persisted plans and swaps store immutable nutrition and target snapshots after a feasible or optimal result.

Deferred solver work remains: expanded portion options, additional soft-objective scoring, solver diagnostics endpoints, and broader production regression fixtures.

## Inputs

### User Profile

- Age or birth date.
- Sex.
- Height.
- Weight.
- Estimated lean mass when available.
- Activity level.
- Goal.
- Target rate.
- Cooking time budget.
- Available equipment.
- Dietary restrictions and allergies.
- Preferences.

### Nutrition Targets

- Calories.
- Protein.
- Carbohydrates.
- Fat.
- Fiber if tracked.
- Micronutrient targets and upper limits.
- Target tolerance policy.

### Plan Request

- Date or date range.
- Meal slots.
- Meals per day.
- Locked meals.
- Natural-language request after AI parsing, if supplied.
- Swap target item, if this is a swap.
- Logged deviations that should affect the next plan.

### Recipe Candidates

Only structured and verified recipes are eligible:

- Ingredients map to verified foods.
- Quantities and units are known.
- Nutrition snapshot exists.
- Required equipment is known.
- Total time is known.
- Restriction and preference tags are known.

## Hard Constraints

Hard constraints cannot be violated.

### Safety and Dietary

- Exclude allergens and strict dietary restrictions.
- Exclude foods the user marked as never allowed.
- Exclude recipes with unknown nutrition when solver-eligible nutrition is required.
- Respect medical or safety exclusions if supported in future versions.

### Nutrition

- Future persisted plan validation should enforce or reject plans according to configured nutrition policy.
- The current non-persisted solver preview treats calories, macros, micronutrient shortfall, and applicable upper-limit excess as objective penalties and reports compliance metadata.
- Total calories and macros report against the planned +/- 5% preferred band.
- Tracked micronutrients report coverage against current RDA/AI targets.
- Nutrient upper limits are reported and penalized only where current metadata supports applying them to food-derived totals.

### Meal Structure

- Required meal slots must be filled.
- Locked meals must remain unchanged.
- Serving sizes must be within allowed portion bounds.
- Duplicate rules must be respected where configured.

### Time and Equipment

- Recipe total time must fit the user's meal-level time budget.
- Daily cooking time must fit the user's daily time budget where enabled.
- Recipes requiring unavailable equipment are excluded.
- Recipes tagged quick must complete within the configured quick threshold, planned as 20 minutes or less.

### Data Integrity

- Candidate recipe nutrition must be calculated from recipe ingredients.
- Plan totals must be recalculated from selected items and portions.
- AI output cannot satisfy a nutrition constraint.

## Soft Constraints

Soft constraints contribute to the objective score.

- Minimize calorie deviation from target.
- Minimize macro deviation from target.
- Maximize preference match.
- Maximize cuisine and protein variety.
- Minimize repeated recipes across the week.
- Prefer shorter prep time for busy users.
- Prefer recipes using existing planned ingredients.
- Prefer lower cost if price data becomes available.
- Prefer recipes with simpler equipment.
- Prefer meal-type fit, such as breakfast-like recipes for breakfast.
- Prefer higher confidence nutrition data sources.

Soft constraints may be weighted by product policy and tuned using solver run outcomes.

## Candidate Filtering

The current dietary extension requires explicit `pescatarian` and `halal` recipe tags
when requested by the saved profile. Supported profile allergens are checked against
reviewed ingredient-food metadata. Unknown profile allergy codes, unreviewed foods, and
known conflicts are excluded before OR-Tools. Nothing is inferred from ingredient names.
The same service is reused by previews, daily plans, swaps, weekly plans, and adaptive
planning; solver mechanics and nutrition calculations are unchanged. Metadata describes
ingredient content only, with no cross-contact or medical safety guarantee.

Candidate filtering reduces the solver problem before OR-Tools.

Filtering stages:

1. Select recipe status: active and solver eligible.
2. Match meal type and requested meal slots.
3. Exclude dietary restrictions and allergens.
4. Exclude unavailable equipment.
5. Apply time budget.
6. Apply explicit request constraints, such as no dairy or different protein.
7. Apply broad nutrition feasibility ranges per serving.
8. Apply preference scoring.
9. Limit to a ranked candidate pool per meal slot.

The filter should produce enough candidates for solver feasibility while keeping solve time predictable.

## OR-Tools Optimization

### Model Type

Use Google OR-Tools CP-SAT for discrete recipe selection and portion choices.

Current solver preview approach:

- Decision variable for candidate recipe selection per meal slot.
- Exactly one selected candidate per required meal slot.
- Zero or one selected candidate per optional meal slot.
- Fixed `1.0` recipe serving per selected meal.
- Same recipe cannot fill multiple slots in one day.
- Optional locked nutrition can be supplied as base daily totals for swap solving.
- Locked meal item identities are orchestrated by the swap service, while the solver optimizes open slots against final full-day totals.

Future portion expansion:

- Add discrete portion multipliers such as `0.5`, `0.75`, `1.0`, `1.25`, and `1.5`.
- Keep arbitrary floating serving amounts out of the solver.

### Nutrition Scaling

Recipe nutrition should be precomputed per allowed portion option to keep the CP-SAT model integer-friendly.

Examples:

- 0.5 serving.
- 0.75 serving.
- 1.0 serving.
- 1.25 servings.
- 1.5 servings.

Nutrients can be scaled to integer units for solver use, such as tenths of grams or whole milligrams, then converted back for display.

### Constraints

The solver adds constraints for:

- Meal slot coverage.
- Optional slot maximums.
- Same-day recipe reuse.
- Fixed serving amount.
- Candidate eligibility inherited from recipe candidate filtering.
- Time, equipment, dietary restriction, disliked food, and explicit exclusions through candidate filtering.
- Locked meal nutrition through `DailyPlanSolverInput.locked_nutrition`.
- Duplicate limits.
- Explicit swap exclusions.

For the current preview and swap flows, calorie, macro, and micronutrient precision is optimized through objective penalties and reported with compliance metadata rather than enforced as hard feasibility bands. This lets the API return the closest structurally valid day when exact +/- 5% nutrition precision is impossible.

### Objective

The solver minimizes a weighted objective:

- Nutrition deviation penalties.
- Calorie deviation.
- Protein, carbohydrate, and fat deviation.
- Micronutrient shortfall.
- Applicable upper-limit excess for nutrients whose current metadata represents true `UL` or `CDRR` semantics.
- Deterministic tie-breaking by option order.

Preference mismatch, repetition, time preference, and ingredient waste penalties are deferred.

When nutrition feasibility conflicts with preferences, nutrition wins.

### Infeasibility Handling

If no solution exists:

- Return structured infeasibility reasons where detectable.
- Relax soft constraints first.
- Do not relax allergies, strict restrictions, verified-data requirements, or nutrition validation rules silently.
- Suggest user-facing adjustments such as adding equipment, increasing prep time, widening preferences, or reducing micronutrient strictness only if policy allows.

## Nutrition Validation

Solver output is not trusted until validated.

Validation steps:

1. Recalculate each selected recipe and portion with the nutrition engine.
2. Sum meal, day, and plan totals.
3. Compare totals to target tolerances.
4. Check tracked micronutrient minimums.
5. Check upper limits.
6. Verify all restrictions and equipment constraints still hold.
7. Store validation results and nutrition totals.

Only validated plans can be returned as successful generated plans.

## Meal Swapping

Meal swapping replaces one meal while preserving the day.

Inputs:

- Existing meal plan.
- Item to replace.
- Persisted nutrition snapshots for all locked items.
- Structured swap request constraints.
- Original meal-plan target snapshots.

Flow:

1. Load the persisted generated meal plan for the authenticated user.
2. Reject archived plans.
3. Locate the selected meal-plan item.
4. Lock all other meal items.
5. Compute locked nutrition totals from persisted item nutrient snapshots.
6. Reconstruct solver targets from the plan's saved target snapshots.
7. Filter candidates for the selected meal type and structured request constraints.
8. Exclude the current recipe and locked recipe IDs.
9. Call the existing OR-Tools solver with one open slot and locked nutrition base totals.
10. Update the selected item recipe/name/serving/nutrient snapshots transactionally.
11. Return the updated persisted plan.

The solver objective scores final full-day totals:

```text
locked meal nutrition snapshots + replacement candidate nutrition
```

It does not optimize the replacement meal in isolation.

Swap examples:

- Quick replacement.
- No dairy replacement.
- Different protein, deferred until structured protein-source metadata exists.
- Eating-out style recipe or external meal placeholder, deferred until verified external meals exist.

If a single-meal swap cannot satisfy the day, the API may return:

- No valid swap found.
- `NO_SWAP_CANDIDATE`.
- Valid swap options in a future swap-options endpoint.
- A recommendation to regenerate the full day once regeneration exists.

## Adaptive Next-Day Planning

Adaptive next-day planning reuses the daily solver. It changes solver targets, not recipe eligibility semantics or solver implementation.

Flow:

```text
Source persisted meal plan
    -> active meal logs
    -> actual-minus-target deviation
    -> conservative adjusted target DTO
    -> existing candidate filtering
    -> existing OR-Tools daily solver
    -> optional persisted next-day plan
```

Source requirements:

- The source meal plan must belong to the authenticated user.
- Archived plans cannot be used as adaptation sources.
- Source target snapshots must exist.
- Every source meal-plan item must have an active log.
- Unlogged meals are not assumed eaten.

Deviation and policy:

- Calories and macros compare actual log totals against saved source-plan targets.
- The MVP compensation policy uses `policy_version = adaptive_v1`, `compensation_fraction = 0.25`, a `250 kcal` maximum adjustment, a `10%` source-target maximum adjustment, and a `1200 kcal` minimum adjusted target.
- Over-target days lower tomorrow's calories by the capped fraction. Under-target days raise tomorrow's calories by the capped fraction.
- Protein and fat stay anchored to the source plan targets; carbohydrates fill the remaining adjusted calories.
- Micronutrient shortfalls and overages are reported, but next-day micronutrient targets remain the saved standard target set.

Solver reuse:

- Adaptive preview calls the same candidate-filtering service and `solve_daily_plan` path as daily preview.
- Adaptive generation calls the same daily plan persistence path with an adjusted target override.
- The existing +/- 5% preferred tolerance is evaluated against the adjusted calorie and macro targets.
- Existing request constraints such as meal slots, time, complete nutrition, required nutrients, recipe exclusions, and required/excluded tags remain candidate-filter inputs.
- `ADAPTIVE_PLAN_INFEASIBLE` is returned when the adjusted target and candidate constraints cannot produce a structural solver result for generation.

Persistence:

- Preview does not persist a meal plan.
- Generation persists a normal `meal_plans` row for `source_plan.plan_date + 1 day`.
- Generation also persists one `meal_plan_adaptations` row with source plan, policy, deviation, compensation, and adjusted macro metadata.
- Existing next-day plans are not overwritten.

## Weekly Planning Orchestration

Weekly planning reuses the daily solver instead of creating a second optimizer.

Flow:

```text
Weekly request
    -> seven calendar dates
    -> DailySolverPreviewRequest-compatible payload per date
    -> existing candidate filtering
    -> existing OR-Tools daily solver
    -> existing daily plan persistence
    -> WeeklyMealPlan association
```

Daily targets:

- Each generated day uses the same target-generation logic as normal daily plan creation.
- Weekly planning does not divide or average weekly nutrition targets.
- Each day is optimized against one day's calorie, macro, and micronutrient targets.

Variety rule:

- Before generating a day after the first one, the weekly service adds the previous day's selected recipe IDs to the daily request's explicit exclusions.
- This is an orchestration hard exclusion only for the first attempt.
- If that attempt is infeasible, the day is retried without the variety exclusions.
- Existing safety, dietary, equipment, nutrition completeness, and explicit user constraints are not relaxed.

Transaction rule:

- Weekly creation is atomic.
- If a later day fails, the service rolls back the weekly container and all newly generated daily plans.
- Existing active daily plans in the requested date range are treated as conflicts before solving starts.

Grocery foundation:

- The solver still chooses recipes; grocery aggregation is not part of the objective.
- Ingredient snapshots are written when meal plan items are persisted.
- Grocery preview sums those snapshots by stable `food_id`.
- The formula is `recipe_ingredient.quantity_grams * meal_plan_item.servings`.
- Persisted smart grocery lists reuse the same snapshot aggregation, then allow independent checked state, quantity/category edits, and manual items.
- Store-specific aisle grouping and retailer integrations are deferred.

## Plan Validation Statuses

- `draft`: generated but not accepted.
- `valid`: passes all configured validation checks.
- `invalid`: fails validation and must not be presented as a successful plan.
- `infeasible`: solver could not find a valid plan.
- `needs_review`: generated with non-critical warnings, such as low candidate diversity.

## Solver Metadata

Store:

- Candidate count.
- Selected recipes and portions.
- Solver status.
- Objective value.
- Solve duration.
- Constraint summary.
- Infeasibility reasons.
- Validation deltas.

This metadata supports debugging, customer support, analytics, and future tuning.
