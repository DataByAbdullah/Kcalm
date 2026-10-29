from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter
from uuid import UUID

from ortools.sat.python import cp_model

from app.meal_planning.scaling import scale_amount, scaled_tolerance_bounds, unscale_amount
from app.nutrition.recipe import RECIPE_NUTRIENT_DEFINITION_BY_CODE
from app.services.recipe_candidate_service import RecipeCandidate


CALORIES_CODE = "calories"
PROTEIN_CODE = "protein"
CARBOHYDRATES_CODE = "carbohydrates"
FAT_CODE = "fat"
MACRO_CODES = (PROTEIN_CODE, CARBOHYDRATES_CODE, FAT_CODE)
CORE_NUTRIENT_CODES = (CALORIES_CODE, *MACRO_CODES)
DEFAULT_SOLVER_TIMEOUT_SECONDS = 3.0
DEFAULT_TOLERANCE = 0.05
UPPER_LIMIT_APPLICABLE_TYPES = {"UL", "CDRR"}

OBJECTIVE_NORMALIZATION_FACTOR = 1_000_000
CALORIE_DEVIATION_WEIGHT = 1000
MACRO_DEVIATION_WEIGHT = 1500
MICRONUTRIENT_SHORTFALL_WEIGHT = 300
MICRONUTRIENT_UPPER_EXCESS_WEIGHT = 500


class SolverStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"


class ToleranceStatus(StrEnum):
    WITHIN = "within_tolerance"
    BELOW = "below_tolerance"
    ABOVE = "above_tolerance"


@dataclass(frozen=True)
class MealSlot:
    meal_type: str
    required: bool = True


@dataclass(frozen=True)
class SolverMicronutrientTarget:
    code: str
    name: str
    target: float
    unit: str
    minimum_target: float | None
    upper_limit: float | None
    upper_limit_type: str | None


@dataclass(frozen=True)
class SolverNutritionTargets:
    calories: float
    protein_g: float
    carbohydrates_g: float
    fat_g: float
    micronutrients: list[SolverMicronutrientTarget]


@dataclass(frozen=True)
class SolverConfig:
    tolerance: float = DEFAULT_TOLERANCE
    time_limit_seconds: float = DEFAULT_SOLVER_TIMEOUT_SECONDS


@dataclass(frozen=True)
class DailyPlanSolverInput:
    candidates: list[RecipeCandidate]
    targets: SolverNutritionTargets
    meal_slots: list[MealSlot]
    config: SolverConfig = SolverConfig()
    locked_nutrition: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class SelectedMeal:
    meal_type: str
    recipe_id: UUID
    recipe_name: str
    serving_amount: float
    nutrition: dict[str, float]


@dataclass(frozen=True)
class NutritionDeviation:
    nutrient_code: str
    nutrient_name: str
    target: float
    actual: float
    unit: str
    deviation_amount: float
    deviation_percent: float
    tolerance_lower: float
    tolerance_upper: float
    status: ToleranceStatus


@dataclass(frozen=True)
class MicronutrientCoverage:
    nutrient_code: str
    nutrient_name: str
    target: float
    actual: float
    unit: str
    coverage_percent: float
    met: bool
    upper_limit: float | None
    upper_limit_type: str | None
    upper_limit_applicable: bool
    upper_limit_exceeded: bool


@dataclass(frozen=True)
class DailyPlanSolverResult:
    status: SolverStatus
    meals: list[SelectedMeal]
    daily_totals: dict[str, float]
    targets: SolverNutritionTargets
    deviations: list[NutritionDeviation]
    micronutrient_coverage: list[MicronutrientCoverage]
    within_preferred_tolerance: bool
    objective_value: int | None
    infeasibility_reasons: list[str]
    solve_time_seconds: float
    candidate_count: int


class MealSolverInputError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateOption:
    slot_index: int
    meal_type: str
    candidate_index: int
    candidate: RecipeCandidate
    nutrition_scaled: dict[str, int]


def default_meal_slots() -> list[MealSlot]:
    return [
        MealSlot("breakfast", required=True),
        MealSlot("lunch", required=True),
        MealSlot("dinner", required=True),
        MealSlot("snack", required=False),
    ]


def solve_daily_plan(solver_input: DailyPlanSolverInput) -> DailyPlanSolverResult:
    started_at = perf_counter()
    validate_solver_input(solver_input)
    required_codes = required_nutrient_codes(solver_input.targets)
    options, malformed_candidate_ids = build_candidate_options(
        candidates=solver_input.candidates,
        meal_slots=solver_input.meal_slots,
        required_codes=required_codes,
    )

    structural_reasons = structural_infeasibility_reasons(
        solver_input=solver_input,
        options=options,
        malformed_candidate_ids=malformed_candidate_ids,
    )
    if structural_reasons:
        return infeasible_result(
            solver_input=solver_input,
            reasons=structural_reasons,
            solve_time_seconds=perf_counter() - started_at,
        )

    model = cp_model.CpModel()
    variables = [
        model.NewBoolVar(f"slot_{option.slot_index}_candidate_{option.candidate_index}")
        for option in options
    ]

    for slot_index, slot in enumerate(solver_input.meal_slots):
        slot_variables = [
            variables[index]
            for index, option in enumerate(options)
            if option.slot_index == slot_index
        ]
        if not slot_variables and not slot.required:
            continue
        if slot.required:
            model.Add(sum(slot_variables) == 1)
        else:
            model.Add(sum(slot_variables) <= 1)

    candidate_indexes = sorted({option.candidate_index for option in options})
    for candidate_index in candidate_indexes:
        candidate_variables = [
            variables[index]
            for index, option in enumerate(options)
            if option.candidate_index == candidate_index
        ]
        model.Add(sum(candidate_variables) <= 1)

    locked_totals_scaled = locked_nutrition_scaled(
        locked_nutrition=solver_input.locked_nutrition,
        required_codes=required_codes,
    )
    totals = {
        code: locked_totals_scaled[code] + sum(
            option.nutrition_scaled[code] * variables[index]
            for index, option in enumerate(options)
        )
        for code in required_codes
    }

    objective_terms = []
    add_absolute_deviation_terms(
        model=model,
        objective_terms=objective_terms,
        total=totals[CALORIES_CODE],
        target_scaled=scale_amount(solver_input.targets.calories),
        coefficient=objective_coefficient(
            weight=CALORIE_DEVIATION_WEIGHT,
            target=solver_input.targets.calories,
        ),
        name=CALORIES_CODE,
        max_total=max_scaled_total(
            options=options,
            nutrient_code=CALORIES_CODE,
            locked_total=locked_totals_scaled[CALORIES_CODE],
        ),
    )
    for code, amount in macro_targets_by_code(solver_input.targets).items():
        add_absolute_deviation_terms(
            model=model,
            objective_terms=objective_terms,
            total=totals[code],
            target_scaled=scale_amount(amount),
            coefficient=objective_coefficient(
                weight=MACRO_DEVIATION_WEIGHT,
                target=amount,
            ),
            name=code,
            max_total=max_scaled_total(
                options=options,
                nutrient_code=code,
                locked_total=locked_totals_scaled[code],
            ),
        )

    for micronutrient in solver_input.targets.micronutrients:
        minimum_target = micronutrient.minimum_target or micronutrient.target
        target_scaled = scale_amount(minimum_target)
        shortfall = model.NewIntVar(
            0,
            max(target_scaled, 1),
            f"{micronutrient.code}_shortfall",
        )
        model.Add(shortfall >= target_scaled - totals[micronutrient.code])
        objective_terms.append(
            shortfall
            * objective_coefficient(
                weight=MICRONUTRIENT_SHORTFALL_WEIGHT,
                target=minimum_target,
            )
        )

        if micronutrient_upper_limit_applicable(micronutrient):
            upper_scaled = scale_amount(micronutrient.upper_limit or 0)
            max_total = max_scaled_total(
                options=options,
                nutrient_code=micronutrient.code,
                locked_total=locked_totals_scaled[micronutrient.code],
            )
            excess = model.NewIntVar(
                0,
                max(max_total - upper_scaled, 0),
                f"{micronutrient.code}_upper_excess",
            )
            model.Add(excess >= totals[micronutrient.code] - upper_scaled)
            objective_terms.append(
                excess
                * objective_coefficient(
                    weight=MICRONUTRIENT_UPPER_EXCESS_WEIGHT,
                    target=micronutrient.upper_limit or 1,
                )
            )

    for index, variable in enumerate(variables):
        objective_terms.append(variable * (index + 1))

    model.Minimize(sum(objective_terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = solver_input.config.time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0

    raw_status = solver.Solve(model)
    status = map_cp_solver_status(raw_status)
    solve_time_seconds = perf_counter() - started_at
    if status is SolverStatus.INFEASIBLE:
        return infeasible_result(
            solver_input=solver_input,
            reasons=["solver_no_structurally_valid_assignment"],
            solve_time_seconds=solve_time_seconds,
        )

    selected_options = [
        option for index, option in enumerate(options) if solver.BooleanValue(variables[index])
    ]
    meals = selected_meals_from_options(selected_options)
    daily_totals = daily_totals_from_meals(
        meals=meals,
        required_codes=required_codes,
        locked_nutrition=solver_input.locked_nutrition,
    )
    deviations = build_macro_deviations(
        daily_totals=daily_totals,
        targets=solver_input.targets,
        tolerance=solver_input.config.tolerance,
    )
    micronutrient_coverage = build_micronutrient_coverage(
        daily_totals=daily_totals,
        micronutrient_targets=solver_input.targets.micronutrients,
    )
    within_preferred_tolerance = all(
        deviation.status is ToleranceStatus.WITHIN for deviation in deviations
    ) and all(
        coverage.met and not coverage.upper_limit_exceeded
        for coverage in micronutrient_coverage
    )

    return DailyPlanSolverResult(
        status=status,
        meals=meals,
        daily_totals=daily_totals,
        targets=solver_input.targets,
        deviations=deviations,
        micronutrient_coverage=micronutrient_coverage,
        within_preferred_tolerance=within_preferred_tolerance,
        objective_value=int(solver.ObjectiveValue()),
        infeasibility_reasons=[],
        solve_time_seconds=solve_time_seconds,
        candidate_count=len(solver_input.candidates),
    )


def validate_solver_input(solver_input: DailyPlanSolverInput) -> None:
    if not solver_input.meal_slots:
        raise MealSolverInputError("At least one meal slot is required.")
    if solver_input.config.tolerance <= 0 or solver_input.config.tolerance >= 1:
        raise MealSolverInputError("Tolerance must be greater than 0 and less than 1.")
    if solver_input.config.time_limit_seconds <= 0:
        raise MealSolverInputError("Solver time limit must be greater than 0.")

    targets = solver_input.targets
    target_values = {
        CALORIES_CODE: targets.calories,
        PROTEIN_CODE: targets.protein_g,
        CARBOHYDRATES_CODE: targets.carbohydrates_g,
        FAT_CODE: targets.fat_g,
    }
    target_values.update(
        {
            micronutrient.code: micronutrient.minimum_target or micronutrient.target
            for micronutrient in targets.micronutrients
        }
    )
    invalid_targets = [
        code for code, amount in target_values.items() if amount is None or amount <= 0
    ]
    if invalid_targets:
        raise MealSolverInputError(
            f"Solver targets must be positive for: {', '.join(sorted(invalid_targets))}"
        )
    invalid_locked_nutrition = [
        code for code, amount in solver_input.locked_nutrition.items()
        if amount is None or amount < 0
    ]
    if invalid_locked_nutrition:
        raise MealSolverInputError(
            "Locked nutrition amounts must be non-negative for: "
            f"{', '.join(sorted(invalid_locked_nutrition))}"
        )


def required_nutrient_codes(targets: SolverNutritionTargets) -> tuple[str, ...]:
    codes = [*CORE_NUTRIENT_CODES]
    codes.extend(micronutrient.code for micronutrient in targets.micronutrients)
    return tuple(dict.fromkeys(codes))


def build_candidate_options(
    candidates: list[RecipeCandidate],
    meal_slots: list[MealSlot],
    required_codes: tuple[str, ...],
) -> tuple[list[CandidateOption], set[UUID]]:
    options: list[CandidateOption] = []
    malformed_candidate_ids: set[UUID] = set()
    for candidate_index, candidate in enumerate(candidates):
        nutrition_scaled = candidate_nutrition_scaled(
            candidate=candidate,
            required_codes=required_codes,
        )
        if nutrition_scaled is None:
            malformed_candidate_ids.add(candidate.recipe_id)
            continue

        for slot_index, slot in enumerate(meal_slots):
            if slot.meal_type in candidate.meal_tags:
                options.append(
                    CandidateOption(
                        slot_index=slot_index,
                        meal_type=slot.meal_type,
                        candidate_index=candidate_index,
                        candidate=candidate,
                        nutrition_scaled=nutrition_scaled,
                    )
                )

    return options, malformed_candidate_ids


def candidate_nutrition_scaled(
    candidate: RecipeCandidate,
    required_codes: tuple[str, ...],
) -> dict[str, int] | None:
    nutrients_by_code = {nutrient.code: nutrient for nutrient in candidate.per_serving_nutrition}
    nutrition_scaled: dict[str, int] = {}
    for code in required_codes:
        nutrient = nutrients_by_code.get(code)
        definition = RECIPE_NUTRIENT_DEFINITION_BY_CODE.get(code)
        if nutrient is None or definition is None:
            return None
        if not nutrient.complete or nutrient.amount < 0 or nutrient.unit != definition.unit:
            return None
        nutrition_scaled[code] = scale_amount(nutrient.amount)
    # Carry known, non-target nutrients into snapshots without inventing solver targets.
    for code, nutrient in nutrients_by_code.items():
        definition = RECIPE_NUTRIENT_DEFINITION_BY_CODE.get(code)
        if (code not in nutrition_scaled and definition is not None and nutrient.complete
                and nutrient.amount >= 0 and nutrient.unit == definition.unit):
            nutrition_scaled[code] = scale_amount(nutrient.amount)
    return nutrition_scaled


def locked_nutrition_scaled(
    locked_nutrition: dict[str, float],
    required_codes: tuple[str, ...],
) -> dict[str, int]:
    return {
        code: scale_amount(locked_nutrition.get(code, 0))
        for code in required_codes
    }


def structural_infeasibility_reasons(
    solver_input: DailyPlanSolverInput,
    options: list[CandidateOption],
    malformed_candidate_ids: set[UUID],
) -> list[str]:
    reasons: list[str] = []
    if not solver_input.candidates:
        reasons.append("no_eligible_candidates")
        return reasons
    if len(malformed_candidate_ids) == len(solver_input.candidates):
        reasons.append("all_candidate_nutrition_malformed")

    for slot_index, slot in enumerate(solver_input.meal_slots):
        if not slot.required:
            continue
        if not any(option.slot_index == slot_index for option in options):
            reasons.append(f"missing_meal_slot_candidate:{slot.meal_type}")
    return reasons


def add_absolute_deviation_terms(
    model: cp_model.CpModel,
    objective_terms: list,
    total,
    target_scaled: int,
    coefficient: int,
    name: str,
    max_total: int,
) -> None:
    upper_bound = max(max_total, target_scaled)
    positive = model.NewIntVar(0, upper_bound, f"{name}_positive_deviation")
    negative = model.NewIntVar(0, upper_bound, f"{name}_negative_deviation")
    model.Add(total - target_scaled == positive - negative)
    objective_terms.extend([positive * coefficient, negative * coefficient])


def objective_coefficient(weight: int, target: float) -> int:
    target_scaled = max(scale_amount(target), 1)
    return max(1, weight * OBJECTIVE_NORMALIZATION_FACTOR // target_scaled)


def max_scaled_total(
    options: list[CandidateOption],
    nutrient_code: str,
    locked_total: int = 0,
) -> int:
    return locked_total + sum(option.nutrition_scaled[nutrient_code] for option in options)


def macro_targets_by_code(targets: SolverNutritionTargets) -> dict[str, float]:
    return {
        PROTEIN_CODE: targets.protein_g,
        CARBOHYDRATES_CODE: targets.carbohydrates_g,
        FAT_CODE: targets.fat_g,
    }


def micronutrient_upper_limit_applicable(target: SolverMicronutrientTarget) -> bool:
    return (
        target.upper_limit is not None
        and target.upper_limit_type in UPPER_LIMIT_APPLICABLE_TYPES
    )


def map_cp_solver_status(raw_status: int) -> SolverStatus:
    if raw_status == cp_model.OPTIMAL:
        return SolverStatus.OPTIMAL
    if raw_status == cp_model.FEASIBLE:
        return SolverStatus.FEASIBLE
    return SolverStatus.INFEASIBLE


def selected_meals_from_options(options: list[CandidateOption]) -> list[SelectedMeal]:
    selected = sorted(
        options,
        key=lambda option: (option.slot_index, option.candidate.name.lower(), str(option.candidate.recipe_id)),
    )
    meals: list[SelectedMeal] = []
    for option in selected:
        meals.append(
            SelectedMeal(
                meal_type=option.meal_type,
                recipe_id=option.candidate.recipe_id,
                recipe_name=option.candidate.name,
                serving_amount=1.0,
                nutrition={
                    code: unscale_amount(amount)
                    for code, amount in option.nutrition_scaled.items()
                },
            )
        )
    return meals


def daily_totals_from_meals(
    meals: list[SelectedMeal],
    required_codes: tuple[str, ...],
    locked_nutrition: dict[str, float] | None = None,
) -> dict[str, float]:
    locked_nutrition = locked_nutrition or {}
    additional_codes = set.intersection(*(set(meal.nutrition) for meal in meals)) if meals else set()
    if locked_nutrition:
        additional_codes &= set(locked_nutrition)
    total_codes = list(dict.fromkeys([*required_codes, *sorted(additional_codes)]))
    totals_scaled = {
        code: scale_amount(locked_nutrition.get(code, 0))
        for code in total_codes
    }
    for meal in meals:
        for code in total_codes:
            totals_scaled[code] += scale_amount(meal.nutrition.get(code, 0))
    return {code: unscale_amount(amount) for code, amount in totals_scaled.items()}


def build_macro_deviations(
    daily_totals: dict[str, float],
    targets: SolverNutritionTargets,
    tolerance: float,
) -> list[NutritionDeviation]:
    target_rows = [
        (CALORIES_CODE, "Calories", targets.calories, "kcal"),
        (PROTEIN_CODE, "Protein", targets.protein_g, "g"),
        (CARBOHYDRATES_CODE, "Carbohydrates", targets.carbohydrates_g, "g"),
        (FAT_CODE, "Fat", targets.fat_g, "g"),
    ]
    deviations: list[NutritionDeviation] = []
    for code, name, target, unit in target_rows:
        actual = daily_totals.get(code, 0)
        lower_scaled, upper_scaled = scaled_tolerance_bounds(target, tolerance)
        lower = unscale_amount(lower_scaled)
        upper = unscale_amount(upper_scaled)
        if actual < lower:
            status = ToleranceStatus.BELOW
        elif actual > upper:
            status = ToleranceStatus.ABOVE
        else:
            status = ToleranceStatus.WITHIN
        deviation_amount = actual - target
        deviations.append(
            NutritionDeviation(
                nutrient_code=code,
                nutrient_name=name,
                target=target,
                actual=actual,
                unit=unit,
                deviation_amount=deviation_amount,
                deviation_percent=(deviation_amount / target) * 100,
                tolerance_lower=lower,
                tolerance_upper=upper,
                status=status,
            )
        )
    return deviations


def build_micronutrient_coverage(
    daily_totals: dict[str, float],
    micronutrient_targets: list[SolverMicronutrientTarget],
) -> list[MicronutrientCoverage]:
    coverage: list[MicronutrientCoverage] = []
    for target in micronutrient_targets:
        minimum_target = target.minimum_target or target.target
        actual = daily_totals.get(target.code, 0)
        upper_limit_applicable = micronutrient_upper_limit_applicable(target)
        coverage.append(
            MicronutrientCoverage(
                nutrient_code=target.code,
                nutrient_name=target.name,
                target=minimum_target,
                actual=actual,
                unit=target.unit,
                coverage_percent=(actual / minimum_target) * 100,
                met=actual >= minimum_target,
                upper_limit=target.upper_limit,
                upper_limit_type=target.upper_limit_type,
                upper_limit_applicable=upper_limit_applicable,
                upper_limit_exceeded=(
                    upper_limit_applicable
                    and target.upper_limit is not None
                    and actual > target.upper_limit
                ),
            )
        )
    return coverage


def infeasible_result(
    solver_input: DailyPlanSolverInput,
    reasons: list[str],
    solve_time_seconds: float,
) -> DailyPlanSolverResult:
    required_codes = required_nutrient_codes(solver_input.targets)
    daily_totals = {
        code: unscale_amount(amount)
        for code, amount in locked_nutrition_scaled(
            locked_nutrition=solver_input.locked_nutrition,
            required_codes=required_codes,
        ).items()
    }
    deviations = build_macro_deviations(
        daily_totals=daily_totals,
        targets=solver_input.targets,
        tolerance=solver_input.config.tolerance,
    )
    micronutrient_coverage = build_micronutrient_coverage(
        daily_totals=daily_totals,
        micronutrient_targets=solver_input.targets.micronutrients,
    )
    return DailyPlanSolverResult(
        status=SolverStatus.INFEASIBLE,
        meals=[],
        daily_totals=daily_totals,
        targets=solver_input.targets,
        deviations=deviations,
        micronutrient_coverage=micronutrient_coverage,
        within_preferred_tolerance=False,
        objective_value=None,
        infeasibility_reasons=reasons,
        solve_time_seconds=solve_time_seconds,
        candidate_count=len(solver_input.candidates),
    )
