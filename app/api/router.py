from fastapi import APIRouter

from app.api.routes import ai
from app.api.routes import auth
from app.api.routes import foods
from app.api.routes import grocery_lists
from app.api.routes import health
from app.api.routes import meal_plans
from app.api.routes import nutrition
from app.api.routes import recipes
from app.api.routes import recipe_execution
from app.api.routes import users
from app.api.routes import weekly_meal_plans


api_router = APIRouter()
api_router.include_router(ai.router, prefix="/ai", tags=["AI"])
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(foods.router, prefix="/foods", tags=["Foods"])
api_router.include_router(grocery_lists.router, prefix="/grocery-lists", tags=["Grocery Lists"])
api_router.include_router(health.router, prefix="/health", tags=["Health"])
api_router.include_router(meal_plans.router, prefix="/meal-plans", tags=["Meal Plans"])
api_router.include_router(nutrition.router, prefix="/nutrition", tags=["Nutrition"])
api_router.include_router(recipes.router, prefix="/recipes", tags=["Recipes"])
api_router.include_router(recipe_execution.router, tags=["Recipe Execution"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(
    weekly_meal_plans.router,
    prefix="/weekly-meal-plans",
    tags=["Weekly Meal Plans"],
)
