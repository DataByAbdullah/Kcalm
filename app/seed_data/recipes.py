from app.seed_data.p0_recipes import P0_RECIPE_SEED_DATA


DEV_RECIPE_SEED_SOURCE = "development_fixture"


DEV_RECIPE_SEED_DATA: list[dict] = [
    {
        "name": "Greek Yogurt Oat Bowl",
        "description": "Development fixture breakfast bowl with yogurt, oats, and banana.",
        "servings": 1,
        "prep_time_minutes": 5,
        "cook_time_minutes": 0,
        "difficulty": "easy",
        "instructions_summary": "Stir yogurt and oats together, then top with sliced banana.",
        "tags": ["breakfast", "quick", "high_protein", "vegetarian", "pescatarian"],
        "equipment": [],
        "ingredients": [
            {
                "source_food_id": "dev_greek_yogurt",
                "quantity_grams": 170,
                "display_quantity": "3/4",
                "display_unit": "cup",
                "preparation_note": "plain",
            },
            {
                "source_food_id": "dev_oats",
                "quantity_grams": 40,
                "display_quantity": "1/2",
                "display_unit": "cup",
                "preparation_note": "dry",
            },
            {
                "source_food_id": "dev_banana",
                "quantity_grams": 60,
                "display_quantity": "1/2",
                "display_unit": "medium",
                "preparation_note": "sliced",
            },
        ],
        "steps": [
            {"instruction": "Add Greek yogurt to a bowl.", "duration_seconds": 30, "timer": False},
            {"instruction": "Stir in oats until evenly mixed.", "duration_seconds": 60, "timer": False},
            {"instruction": "Top with sliced banana and serve.", "duration_seconds": 60, "timer": False},
        ],
    },
    {
        "name": "Chicken Rice Broccoli Bowl",
        "description": "Development fixture quick high-protein lunch bowl.",
        "servings": 1,
        "prep_time_minutes": 5,
        "cook_time_minutes": 10,
        "difficulty": "easy",
        "instructions_summary": "Warm chicken, rice, and broccoli together with olive oil.",
        "tags": ["lunch", "quick", "high_protein", "dairy_free", "gluten_free"],
        "equipment": ["stovetop"],
        "ingredients": [
            {
                "source_food_id": "dev_chicken_breast",
                "quantity_grams": 120,
                "display_quantity": "1",
                "display_unit": "piece",
                "preparation_note": "cooked and sliced",
            },
            {
                "source_food_id": "dev_cooked_rice",
                "quantity_grams": 158,
                "display_quantity": "1",
                "display_unit": "cup",
                "preparation_note": "cooked",
            },
            {
                "source_food_id": "dev_broccoli",
                "quantity_grams": 91,
                "display_quantity": "1",
                "display_unit": "cup",
                "preparation_note": "chopped",
            },
            {
                "source_food_id": "dev_olive_oil",
                "quantity_grams": 5,
                "display_quantity": "1",
                "display_unit": "tsp",
                "preparation_note": "for warming",
            },
        ],
        "steps": [
            {"instruction": "Warm olive oil in a pan over medium heat.", "duration_seconds": 60, "timer": True},
            {"instruction": "Add chicken, rice, and broccoli.", "duration_seconds": 60, "timer": False},
            {"instruction": "Cook until hot throughout.", "duration_seconds": 480, "timer": True},
        ],
    },
    {
        "name": "Salmon Potato Spinach Plate",
        "description": "Development fixture dinner with salmon, potato, and spinach.",
        "servings": 1,
        "prep_time_minutes": 10,
        "cook_time_minutes": 25,
        "difficulty": "medium",
        "instructions_summary": "Roast salmon and potato, then wilt spinach.",
        "tags": ["dinner", "high_protein", "dairy_free", "gluten_free", "pescatarian"],
        "equipment": ["oven", "stovetop"],
        "ingredients": [
            {
                "source_food_id": "dev_salmon",
                "quantity_grams": 150,
                "display_quantity": "1",
                "display_unit": "fillet",
                "preparation_note": "raw or thawed",
            },
            {
                "source_food_id": "dev_potato",
                "quantity_grams": 173,
                "display_quantity": "1",
                "display_unit": "medium",
                "preparation_note": "cubed",
            },
            {
                "source_food_id": "dev_spinach",
                "quantity_grams": 60,
                "display_quantity": "2",
                "display_unit": "cups",
                "preparation_note": "raw",
            },
            {
                "source_food_id": "dev_olive_oil",
                "quantity_grams": 10,
                "display_quantity": "2",
                "display_unit": "tsp",
                "preparation_note": "divided",
            },
        ],
        "steps": [
            {"instruction": "Heat oven and place salmon and potato on a tray.", "duration_seconds": 180, "timer": False},
            {"instruction": "Roast until salmon is cooked and potato is tender.", "duration_seconds": 1200, "timer": True},
            {"instruction": "Wilt spinach on the stovetop with remaining oil.", "duration_seconds": 240, "timer": True},
        ],
    },
    {
        "name": "Banana Oat Milk Smoothie",
        "description": "Development fixture quick snack smoothie.",
        "servings": 1,
        "prep_time_minutes": 5,
        "cook_time_minutes": 0,
        "difficulty": "easy",
        "instructions_summary": "Blend milk, banana, and oats until smooth.",
        "tags": ["snack", "quick", "vegetarian"],
        "equipment": ["blender"],
        "ingredients": [
            {
                "source_food_id": "dev_milk",
                "quantity_grams": 244,
                "display_quantity": "1",
                "display_unit": "cup",
                "preparation_note": "cold",
            },
            {
                "source_food_id": "dev_banana",
                "quantity_grams": 118,
                "display_quantity": "1",
                "display_unit": "medium",
                "preparation_note": "peeled",
            },
            {
                "source_food_id": "dev_oats",
                "quantity_grams": 20,
                "display_quantity": "1/4",
                "display_unit": "cup",
                "preparation_note": "dry",
            },
        ],
        "steps": [
            {"instruction": "Add milk, banana, and oats to a blender.", "duration_seconds": 60, "timer": False},
            {"instruction": "Blend until smooth.", "duration_seconds": 60, "timer": True},
        ],
    },
]

DEV_RECIPE_SEED_DATA.extend(P0_RECIPE_SEED_DATA)
