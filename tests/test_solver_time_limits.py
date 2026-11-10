from dataclasses import replace
from uuid import UUID

import pytest
from ortools.sat.python import cp_model

from app.meal_planning import solver as meal_solver
from app.meal_planning.solver import (
    DailyPlanSolverInput, MealSlot, SolverConfig, SolverNutritionTargets,
    SolverStatus, default_meal_slots, solve_daily_plan,
    objective_coefficient,
)
from app.meal_planning.scaling import scale_amount
from tests.test_meal_solver import candidate, nutrient_amounts


def solver_input(count=4, **kwargs):
    slots = default_meal_slots(count)
    return DailyPlanSolverInput(
        candidates=[candidate(slot.meal_type, [slot.meal_type], nutrient_amounts(
            calories=400, protein=30, carbohydrates=50, fat=10,
        )) for slot in slots],
        targets=SolverNutritionTargets(3719, 200, 400, 110, []),
        meal_slots=slots, **kwargs,
    )


def timeout_optimization(monkeypatch):
    solve = cp_model.CpSolver.Solve

    def solve_or_timeout(self, model, *args, **kwargs):
        if model.HasObjective():
            return cp_model.UNKNOWN
        return solve(self, model, *args, **kwargs)

    monkeypatch.setattr(cp_model.CpSolver, "Solve", solve_or_timeout)


def test_unknown_without_an_incumbent_is_a_timeout_not_infeasibility(monkeypatch):
    monkeypatch.setattr(cp_model.CpSolver, "Solve", lambda *args, **kwargs: cp_model.UNKNOWN)
    result = solve_daily_plan(solver_input())

    assert result.status is SolverStatus.UNKNOWN
    assert result.infeasibility_reasons == ["solver_time_limit_exceeded"]
    assert result.meals == [] and result.objective_value is None


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_optimization_timeout_returns_verified_scaled_meals(monkeypatch, count):
    timeout_optimization(monkeypatch)
    data = solver_input(count)
    result = solve_daily_plan(data)

    assert result.status is SolverStatus.FEASIBLE
    assert result.infeasibility_reasons == []
    assert [meal.meal_type for meal in result.meals] == [slot.meal_type for slot in data.meal_slots]
    assert len({meal.recipe_id for meal in result.meals}) == count
    assert 0.95 * 3719 <= result.daily_totals["calories"] <= 1.05 * 3719
    for meal in result.meals:
        assert 0.75 <= meal.serving_amount <= meal_solver.MAX_SERVING_AMOUNT
        assert meal.serving_amount * 4 == int(meal.serving_amount * 4)
        assert meal.nutrition["calories"] == 400 * meal.serving_amount
        assert meal.nutrition["protein"] == 30 * meal.serving_amount
    for code, amount in result.daily_totals.items():
        assert amount == pytest.approx(sum(meal.nutrition[code] for meal in result.meals))
    assert isinstance(result.objective_value, int)


def test_unknown_feasibility_can_be_recovered_during_optimization(monkeypatch):
    solve = cp_model.CpSolver.Solve

    def solve_only_optimization(self, model, *args, **kwargs):
        if not model.HasObjective():
            return cp_model.UNKNOWN
        return solve(self, model, *args, **kwargs)

    monkeypatch.setattr(cp_model.CpSolver, "Solve", solve_only_optimization)
    result = solve_daily_plan(solver_input(2))
    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert len(result.meals) == 2


def test_preferred_band_infeasibility_does_not_reject_a_hard_feasible_fallback(monkeypatch):
    timeout_optimization(monkeypatch)
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[candidate("Hard-band-only", ["dinner"], nutrient_amounts(calories=100))],
        targets=SolverNutritionTargets(880, 80, 80, 40, []),
        meal_slots=[MealSlot("dinner")],
    ))
    assert result.status is SolverStatus.FEASIBLE
    assert result.daily_totals["calories"] == 800
    assert result.meals[0].serving_amount == 8
    assert result.infeasibility_reasons == []


def test_two_stages_share_one_budget_and_pass_a_complete_hint(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(meal_solver, "perf_counter", lambda: clock[0])
    solve = cp_model.CpSolver.Solve
    limits = []

    def record_solve(self, model, *args, **kwargs):
        limits.append(self.parameters.max_time_in_seconds)
        assert self.parameters.num_search_workers == 1 and self.parameters.random_seed == 0
        if model.HasObjective():
            assert len(model.Proto().solution_hint.vars) == len(model.Proto().variables)
        status = solve(self, model, *args, **kwargs)
        clock[0] += 0.3 if model.HasObjective() else 0.2
        return status

    monkeypatch.setattr(cp_model.CpSolver, "Solve", record_solve)
    result = solve_daily_plan(solver_input(2, config=SolverConfig(time_limit_seconds=2)))
    assert limits == pytest.approx([0.3, 1.8])
    assert result.solve_time_seconds == pytest.approx(0.5)


def test_feasibility_excludes_objective_variables_and_constructs_a_valid_complete_hint(monkeypatch):
    solve = cp_model.CpSolver.Solve
    stages = []

    def inspect_model(self, model, *args, **kwargs):
        stages.append(model.HasObjective())
        if not model.HasObjective():
            assert all(variable.name.startswith("slot_") and list(variable.domain) == [0, 1]
                       for variable in model.Proto().variables)
        else:
            pinned = model.Clone()
            pinned.ClearObjective()
            hint = model.Proto().solution_hint
            assert len(hint.vars) == len(model.Proto().variables)
            for index, value in zip(hint.vars, hint.values, strict=True):
                pinned.Add(pinned.GetIntVarFromProtoIndex(index) == value)
            verifier = meal_solver.bounded_solver(1)
            assert solve(verifier, pinned) in {cp_model.OPTIMAL, cp_model.FEASIBLE}
        return solve(self, model, *args, **kwargs)

    monkeypatch.setattr(cp_model.CpSolver, "Solve", inspect_model)
    data = solver_input(2)
    result = solve_daily_plan(replace(data, locked_nutrition={"calories": 200, "protein": 10}))
    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert stages == [False, True]


def test_fallback_objective_stays_integer_exact_above_float_precision(monkeypatch):
    from tests.test_meal_solver import targets

    timeout_optimization(monkeypatch)
    nutrition_targets = targets(calories=400, protein=30, carbohydrates=50, fat=10, calcium=1)
    nutrition_targets = replace(nutrition_targets, micronutrients=[
        replace(target, upper_limit=1) for target in nutrition_targets.micronutrients if target.code == "calcium"
    ])
    result = solve_daily_plan(DailyPlanSolverInput(
        candidates=[candidate("Large excess", ["dinner"], nutrient_amounts(
            calories=400, protein=30, carbohydrates=50, fat=10, calcium=100_000_000,
        ))],
        targets=nutrition_targets, meal_slots=[MealSlot("dinner")],
    ))
    assert result.status is SolverStatus.FEASIBLE
    expected = (scale_amount(100_000_000) - scale_amount(1)) * objective_coefficient(500, 1) + 2
    assert result.objective_value == expected > 2**53


def test_random_recipe_uuid_order_does_not_change_model_order(monkeypatch):
    data = solver_input(2)
    solve = cp_model.CpSolver.Solve
    models = []

    def record_solve(self, model, *args, **kwargs):
        models.append(str(model.Proto()))
        return solve(self, model, *args, **kwargs)

    monkeypatch.setattr(cp_model.CpSolver, "Solve", record_solve)
    first = replace(data, candidates=[replace(recipe, recipe_id=UUID(int=index + 1))
                                      for index, recipe in enumerate(data.candidates)])
    second = replace(data, candidates=[replace(recipe, recipe_id=UUID(int=10 - index))
                                       for index, recipe in enumerate(data.candidates)])
    solve_daily_plan(first)
    first_models = list(models)
    models.clear()
    solve_daily_plan(second)
    assert models == first_models
