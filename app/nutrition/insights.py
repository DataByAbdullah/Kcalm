"""Transparent product alignment scores, not clinical or health assessments."""
from dataclasses import dataclass
from math import isfinite


MACRO_FIELDS = ("protein_g", "carbs_g", "fat_g")
TARGET_FIELDS = ("calories", *MACRO_FIELDS)


@dataclass(frozen=True)
class NutritionInsightDay:
    actual: dict[str, float | None]
    targets: dict[str, float] | None
    planned_meals: int = 0
    logged_meals: int = 0
    macro_data_complete: bool = True
    target_source: str | None = None


def valid_targets(day: NutritionInsightDay) -> bool:
    return day.targets is not None and all(
        field in day.targets and isfinite(day.targets[field]) and day.targets[field] > 0
        for field in TARGET_FIELDS
    )


def valid_actual(day: NutritionInsightDay) -> bool:
    return day.macro_data_complete and all(
        day.actual.get(field) is not None and isfinite(day.actual[field]) and day.actual[field] >= 0
        for field in TARGET_FIELDS
    )


def adherence(actual: float, target: float) -> float:
    return max(0.0, 100.0 * (1.0 - abs(actual - target) / target))


def build_nutrition_summary(days: list[NutritionInsightDay], days_in_range: int) -> dict:
    if days_in_range < 1 or len(days) > days_in_range:
        raise ValueError("Nutrition insight days must fit a nonempty calendar range.")
    targeted = [day for day in days if valid_targets(day) and valid_actual(day)]
    scored = [day for day in targeted if day.planned_meals > 0 and day.logged_meals > 0]
    # Missing/unscorable days contribute no score, not a claim of zero actual intake.
    scores = {
        field: sum(adherence(day.actual[field], day.targets[field])
                   * min(day.logged_meals / day.planned_meals, 1.0) for day in scored) / days_in_range
        for field in TARGET_FIELDS
    } if scored else {}
    macro_score = sum(scores[field] for field in MACRO_FIELDS) / 3 if scores else None
    planned_meals = sum(day.planned_meals for day in days)
    logged_meals = sum(min(day.logged_meals, day.planned_meals) for day in days)
    reason = None
    if not scored:
        if not days:
            reason = "no_recorded_nutrition"
        elif not any(valid_targets(day) for day in days):
            reason = "targets_unavailable"
        elif not targeted:
            reason = "nutrient_data_incomplete"
        else:
            reason = "meal_logging_unverified"

    def average(field, source):
        return round(sum(getattr(day, source)[field] for day in targeted) / len(targeted), 2) if targeted else None

    return {
        "formula_version": "recorded_plan_alignment_v1",
        "nutrition_score": round((scores["calories"] + macro_score) / 2, 2) if scores else None,
        "unavailable_reason": reason,
        "target_sources": sorted({day.target_source for day in targeted if day.target_source}),
        "calorie_adherence": {
            "score": round(scores["calories"], 2) if scores else None,
            "average_actual_calories": average("calories", "actual"),
            "average_target_calories": average("calories", "targets"),
            "logged_days": len(targeted),
        },
        "macro_balance": {
            "score": round(macro_score, 2) if macro_score is not None else None,
            **{f"{name}_adherence_percent": round(scores[field], 2) if scores else None
               for name, field in zip(("protein", "carbs", "fat"), MACRO_FIELDS)},
        },
        "data_completeness": {
            "logged_days": len(days),
            "days_in_range": days_in_range,
            "percentage": round(len(days) * 100 / days_in_range, 2),
            "scored_days": len(scored),
            "unscored_days": len(days) - len(scored),
            "planned_meals": planned_meals,
            "logged_planned_meals": logged_meals,
            "meal_logging_percentage": round(logged_meals * 100 / planned_meals, 2) if planned_meals else None,
        },
    }
