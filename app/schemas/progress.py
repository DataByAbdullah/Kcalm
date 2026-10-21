from datetime import date

from pydantic import BaseModel


class AchievementResponse(BaseModel):
    code: str
    name: str
    current: int
    target: int
    unit: str
    unlocked: bool


class AchievementsResponse(BaseModel):
    items: list[AchievementResponse]


class InsightResponse(BaseModel):
    code: str
    message: str
    values: dict[str, float | int | None]


class InsightsResponse(BaseModel):
    start_date: date
    end_date: date
    logged_nutrition_days: int
    items: list[InsightResponse]
