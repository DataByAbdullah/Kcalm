import pytest

from app.nutrition.insights import NutritionInsightDay, adherence, build_nutrition_summary


TARGETS = {"calories": 2000, "protein_g": 100, "carbs_g": 250, "fat_g": 60}


def day(**overrides):
    return NutritionInsightDay(**{
        "actual": TARGETS.copy(), "targets": TARGETS.copy(),
        "planned_meals": 4, "logged_meals": 4, "target_source": "saved_plan", **overrides,
    })


def test_complete_alignment_is_a_transparent_product_score_not_a_diagnosis():
    summary = build_nutrition_summary([day(), day()], 2)
    assert summary["formula_version"] == "recorded_plan_alignment_v1"
    assert summary["nutrition_score"] == 100
    assert summary["calorie_adherence"]["score"] == 100
    assert summary["macro_balance"]["score"] == 100
    assert summary["data_completeness"]["percentage"] == 100
    assert summary["data_completeness"]["meal_logging_percentage"] == 100


@pytest.mark.parametrize("actual,expected", [(0, 0), (1000, 50), (2000, 100), (3000, 50), (4000, 0), (5000, 0)])
def test_adherence_penalizes_both_under_and_over_target(actual, expected):
    assert adherence(actual, 2000) == expected


def test_score_uses_calorie_and_macro_components_with_equal_weight():
    actual = {"calories": 1500, "protein_g": 100, "carbs_g": 125, "fat_g": 90}
    summary = build_nutrition_summary([day(actual=actual)], 1)
    assert summary["calorie_adherence"]["score"] == 75
    assert summary["macro_balance"]["protein_adherence_percent"] == 100
    assert summary["macro_balance"]["carbs_adherence_percent"] == 50
    assert summary["macro_balance"]["fat_adherence_percent"] == 50
    assert summary["macro_balance"]["score"] == 66.67
    assert summary["nutrition_score"] == 70.83


def test_missing_dates_and_partial_meal_logging_never_receive_perfect_scores():
    summary = build_nutrition_summary([day(logged_meals=1)], 2)
    assert summary["nutrition_score"] == 12.5
    assert summary["calorie_adherence"]["average_actual_calories"] == 2000
    assert summary["data_completeness"]["percentage"] == 50
    assert summary["data_completeness"]["meal_logging_percentage"] == 25


def test_unrelated_unknown_nutrients_do_not_disable_calorie_and_macro_scores():
    actual = {**TARGETS, "fiber_g": None, "added_sugar_g": None, "calcium": None}
    summary = build_nutrition_summary([day(actual=actual)], 1)
    assert summary["nutrition_score"] == 100
    assert summary["calorie_adherence"]["score"] == 100
    assert summary["macro_balance"]["score"] == 100
    assert summary["unavailable_reason"] is None


@pytest.mark.parametrize("days,reason", [
    ([], "no_recorded_nutrition"),
    ([day(targets=None)], "targets_unavailable"),
    ([day(targets={**TARGETS, "calories": 0})], "targets_unavailable"),
    ([day(planned_meals=0, logged_meals=0)], "meal_logging_unverified"),
    ([day(macro_data_complete=False)], "nutrient_data_incomplete"),
    ([day(actual={**TARGETS, "calories": None})], "nutrient_data_incomplete"),
])
def test_unavailable_data_never_invents_scores(days, reason):
    summary = build_nutrition_summary(days, 1)
    assert summary["nutrition_score"] is None
    assert summary["calorie_adherence"]["score"] is None
    assert summary["macro_balance"]["score"] is None
    assert summary["unavailable_reason"] == reason


@pytest.mark.parametrize("field", TARGETS)
@pytest.mark.parametrize("value", [None, -1, float("nan"), float("inf")])
def test_unknown_or_invalid_formula_input_prevents_scoring(field, value):
    summary = build_nutrition_summary([day(actual={**TARGETS, field: value})], 1)
    assert summary["nutrition_score"] is None
    assert summary["calorie_adherence"]["score"] is None
    assert summary["macro_balance"]["score"] is None
    assert summary["unavailable_reason"] == "nutrient_data_incomplete"


@pytest.mark.parametrize("field", TARGETS)
def test_missing_formula_input_prevents_scoring(field):
    actual = {code: value for code, value in TARGETS.items() if code != field}
    summary = build_nutrition_summary([day(actual=actual)], 1)
    assert summary["nutrition_score"] is None
    assert summary["unavailable_reason"] == "nutrient_data_incomplete"


@pytest.mark.parametrize("field", TARGETS)
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_formula_target_prevents_scoring(field, value):
    summary = build_nutrition_summary([day(targets={**TARGETS, field: value})], 1)
    assert summary["nutrition_score"] is None
    assert summary["calorie_adherence"]["score"] is None
    assert summary["macro_balance"]["score"] is None
    assert summary["unavailable_reason"] == "targets_unavailable"


@pytest.mark.parametrize("field", TARGETS)
def test_missing_formula_target_prevents_scoring(field):
    targets = {code: value for code, value in TARGETS.items() if code != field}
    summary = build_nutrition_summary([day(targets=targets)], 1)
    assert summary["nutrition_score"] is None
    assert summary["unavailable_reason"] == "targets_unavailable"


def test_unscorable_day_does_not_disappear_from_range_denominator():
    summary = build_nutrition_summary([day(), day(macro_data_complete=False)], 2)
    assert summary["nutrition_score"] == 50
    assert summary["data_completeness"]["logged_days"] == 2
    assert summary["data_completeness"]["scored_days"] == 1
    assert summary["data_completeness"]["unscored_days"] == 1


def test_empty_or_inconsistent_calendar_range_is_rejected():
    with pytest.raises(ValueError):
        build_nutrition_summary([], 0)
    with pytest.raises(ValueError):
        build_nutrition_summary([day(), day()], 1)
