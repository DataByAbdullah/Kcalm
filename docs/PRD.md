# Kcalm

## Product Requirements Document

**Subtitle:** Macro- and micro-precise meal planning with animated, done-in-minutes recipes

- **Status:** Draft v0.1
- **Platform:** iOS & Android
- **Owner:** Muhammad Hamdoon T
- **Updated:** Sept 7, 2026

---

## 1. Problem

Whenever someone starts a diet, the hardest part isn't the diet — it's the constant, low-grade decision of what to eat next.

Existing tracking apps stop at the calculator: they'll tell you your calorie and macro targets, then leave you to figure out, three times a day, what actually hits them. That gap is where diets quietly fail. One industry estimate puts a health-focused professional's food-related decisions at roughly 200 a day — what to buy, what to cook, what to swap when plans change — and almost none of that load is currently automated away.

Kcalm's founding premise: remove the deciding, not just the counting. The app should tell a user exactly what to eat, why it fits, and walk them through cooking it in the time they actually have.

## 2. Who it's for

The primary persona is a busy professional, roughly 25–45, who has a clear fitness goal (fat loss, muscle gain, or maintenance), owns a kitchen but rarely has more than 15–20 minutes to use it on a weeknight, and has already tried and abandoned at least one calorie-tracking app because logging felt like unpaid admin work. They don't lack information about nutrition — they lack the bandwidth to apply it meal by meal.

## 3. Core user journey

1. **Onboarding** — Collect biometrics (age, sex, height, weight, activity level), dietary restrictions, cooking time budget, kitchen equipment, and food preferences.
2. **Calculation** — Compute BMR and TDEE, then derive a calorie target from the stated goal, plus macro grams and micronutrient targets.
3. **Goal confirmation** — User reviews and can adjust targets before committing to a plan.
4. **Daily plan generation** — The app assembles a full day of meals that hit macro and micro targets inside the user's time, equipment, and preference constraints.
5. **Swap & regenerate** — One-tap replace any meal under a constraint — quick, no dairy, eating out, different protein — while the day's totals stay on target.
6. **Animated recipe execution** — A step-by-step animated walkthrough with built-in timers guides the actual cooking.
7. **Grocery list** — Auto-generated and aisle-grouped for the week ahead.
8. **Log & adjust** — A quick log of what was actually eaten lets tomorrow's plan compensate automatically.

## 4. Core features

Detailed in the MVP Feature Spec below. At a high level: a precision calculator, a dynamic meal engine, an animated recipe player, a smart grocery list, and adaptive logging.

## 5. Success metrics

- Time to first cooked meal — target under 48 hours from signup
- 7-day plan adherence rate
- Day-30 and day-90 retention
- In-app "how much did you overthink today's meals" micro-survey, trending down over the first month
- App store rating and review sentiment specifically referencing ease of deciding what to eat

## 6. Constraints & assumptions

- Nutrition accuracy depends on a licensed or verified data source, not crowdsourced entries alone
- This is not a medical device and isn't intended to treat eating disorders or diagnosed conditions — needs a clear in-app disclaimer and referral path to professionals
- Animated recipe content has to scale without a full video shoot per recipe
- iOS and Android from day one

## 7. Out of scope for v1

Wearable integration, restaurant or delivery auto-ordering, social and community features, and a human coach/dietitian marketplace are explicitly deferred to later phases.

## 8. Open questions

- "Kcalm" is a working title — trademark and domain availability not yet checked
- Build vs. license the core recipe and nutrition database
- In-house animated step library vs. AI-generated per-recipe video, on cost and scalability
- Pricing tier relative to competitors

---

# Market & Competitive Analysis

- **Status:** Draft v0.1
- **Category:** AI-driven personalized nutrition
- **Updated:** Sept 7, 2026

## 1. Market size & trajectory

| Metric | Value |
|---|---:|
| Market size, 2025 | $1.58B |
| Estimated, 2026 | $2.01B |
| Forecast, 2035 | $17.59B |
| CAGR, 2026–2035 | 27.25% |

Growth is driven by wearable health tech feeding real-time data into apps, rising consumer demand for individualized wellness over generic plans, and AI/ML-powered coaching layered on top of static tracking. North America held 43% of the market in 2025, while Asia-Pacific is forecast to grow fastest.

## 2. Landscape by category

| Category | Examples | Core strength | Gap relative to Kcalm |
|---|---|---|---|
| General trackers | MyFitnessPal, Cronometer | Huge databases (18–20M items); Cronometer tracks 84+ micronutrients | Passive logging — no plan generation or cooking help |
| Macro-plan generators | Eat This Much, Swoodie | Auto-build meal plans to hit macro targets; Swoodie adds photo/barcode logging | Little to no micronutrient precision; recipes are static text |
| Recipe & cooking guidance | Mealime, Yummly, SideChef, Nutrola | Curated or imported recipes; some step-by-step video or photo guidance | Fixed content libraries — can't regenerate a recipe around shifting macro targets |
| Adaptive / agent-style | MacroFactor, Miora | Adjust targets from real progress; Miora auto-executes orders and bookings | Automation without a cooking-at-home experience — execution is outsourced, not taught |

## 3. Signal: PlateJoy's shutdown

> **Market signal:** PlateJoy — a macro-aware meal-planning app — was acquired by RVO Health, pulled from Google Play in March 2025, and shut down on July 1, 2025, with its recipe content folded into the Wellos app.

Read as a caution: meal-planning-only products, without a loop that closes all the way through tracking, adaptation, and execution, struggle to stay sticky enough to stand alone. It's a reason Kcalm's loop has to end at "meal actually cooked," not "plan generated."

## 4. Where Kcalm sits

> **Differentiation thesis:** No researched competitor combines all three of: macro *and* micronutrient precision in one target set, constraint-based real-time plan regeneration, and auto-assembled animated cooking guidance built for a 15-minute window.

Cronometer wins on micronutrient depth but doesn't plan meals. Eat This Much and Swoodie plan meals but skip micros and offer only static recipes. Yummly, SideChef, and Nutrola have strong cooking guidance, but it's tied to a fixed content library rather than a dynamically generated, macro-fit recipe.

## 5. Pricing landscape

| App | Plan | Price |
|---|---|---:|
| Mealime | Pro | $5.99/mo |
| Cronometer | Gold | $8.99/mo · $49.99/yr |
| Eat This Much | Premium | $5–14.99/mo |
| Swoodie | Premium | $9.99/mo · $39.99/yr |
| SideChef | Premium | $9.99/mo |
| MacroFactor | Standard | $11.99/mo |
| MyFitnessPal | Premium | $79.99/yr |

Pricing clusters around $5–12/month, with apps that combine tracking and planning sitting at the top of that range. Kcalm's depth — macro, micro, and animated execution together — could support a $9.99–14.99/month position, to be validated with willingness-to-pay research before launch.

## 6. Risks

- Crowded category — incumbents like Swoodie are already moving toward AI-generated plans and could narrow the gap quickly
- Nutrition data licensing and verification cost
- Animated content has to stay a systems problem (a reusable component library), not a production problem
- Regulatory and liability exposure around any health-adjacent claims

## 7. Sources

- Towards Healthcare — AI in Personalized Nutrition Market Sizing
- Swoodie — Mealime vs. PlateJoy vs. Swoodie (2026)
- Miora — Best AI Nutrition Apps in 2026
- Eat This Much — 12 Best Macro Tracking Apps 2026
- Nutrola — Top 10 Recipe Apps in 2026

---

# MVP Feature Spec

- **Status:** Draft v0.1
- **Platform:** iOS & Android
- **Updated:** Sept 7, 2026

## 1. Scope at a glance

| Phase | Theme | Examples |
|---|---|---|
| v1 (MVP) | Calculate, generate, cook | Onboarding calculator, dynamic daily plan, swap/regenerate, animated recipe player, grocery list, basic logging |
| Phase 2 | Sense & adapt | Photo/barcode logging, restaurant-meal matching, wearable sync, weekly auto-adjustment |
| Phase 3 | Execute | Grocery delivery integration, auto-ordering for off-plan days, coach marketplace, social sharing |

## 2. v1 feature list

### A. Onboarding & Calculation — P0

- Biometric intake — age, sex, height, weight, activity level
- Goal selection (fat loss / muscle gain / maintenance / recomposition) with an adjustable target rate
- BMR via the Mifflin–St Jeor equation, TDEE via an activity multiplier
- Macro split logic by goal — protein anchored to lean mass, a fat floor, carbs filling the remainder
- Micronutrient targets pulled from USDA FoodData Central reference values
- An editable target-review screen before the user commits

### B. Dynamic Meal Engine — P0

- Daily plan assembled from a structured recipe and food database to hit macro and micro targets within the user's stated time, equipment, and preference constraints
- One-tap swap on any meal under a constraint tag — quick, no-X, eating-out, different protein — that keeps the day's totals on target
- Constraint-based generation over a verified recipe set (LLM-assisted templating, not free-form generation), so nutrition numbers stay checkable

### C. Animated Recipe Player — P0 / Core Differentiator

- A reusable animated step-component library (chop, sauté, simmer, whisk, plate) assembled per recipe, rather than filmed per recipe
- Built-in per-step timer or count
- Hands-free "next step" advance, by voice or tap-anywhere
- Target: any recipe tagged "quick" completes in 20 minutes or less

### D. Smart Grocery List — P1

- Auto-generated from the week's plan, grouped by store aisle
- Manual add/remove, with quantities merged across recipes

### E. Adaptive Logging — P1

- Quick confirm ("ate as planned") or a simple correction — swap the eaten item or its portion
- The next day's plan compensates automatically for a logged deviation

## 3. Phase 2 — P2

- Photo-based and barcode logging for off-plan meals
- Restaurant-menu matching
- Wearable integration for recovery- and activity-adjusted targets
- Weekly auto-adjustment based on compliance, similar to MacroFactor's recalibration

## 4. Phase 3 / future

- Grocery delivery API integration — order the list directly
- Auto-ordering for logged "eating out" days within the day's macro budget, in the spirit of Miora's execution layer
- Dietitian/coach marketplace and social or sharing features

## 5. Technical notes

- **Nutrition data:** USDA FoodData Central as the base layer — free, 300,000+ foods, verified — with a supplemental licensed branded-food database evaluated for packaged items
- **Calculation engine:** Mifflin–St Jeor for BMR plus an activity multiplier for TDEE; evidence-based macro ranges by goal; RDA/DRI tables for micronutrient targets
- **Generation approach:** a constraint solver / templated LLM layer over a structured, nutrition-verified recipe database — never free-form LLM output for the numbers themselves
- **Animation approach:** a modular library of animated cooking-technique components, assembled and timed per generated recipe — this is what lets the plan regenerate without a production bottleneck
- **Platform:** iOS and Android; cross-platform framework (React Native vs. Flutter) is still open, and worth deciding once the animation-rendering approach is settled, since it affects which framework handles that layer best

## 6. MVP acceptance criteria

- A new user reaches a confirmed macro/micro target in under 5 minutes from first open
- Every generated day's plan lands within ±5% of the calorie and macro targets, and meets 100% of the micronutrient RDAs it tracks
- Any meal can be swapped without breaking the day's totals
- A "quick"-tagged recipe's animated walkthrough finishes start-to-finish in the time stated on its card
- The grocery list matches the week's finalized plan with no duplicate or missing ingredients

## 7. Ready for wireframing

This spec is scoped enough to move into wireframes for the six core v1 screens:

1. Onboarding
2. Target Review
3. Daily Plan
4. Swap/Regenerate
5. Recipe Player
6. Grocery List
