from app.core.database import SessionLocal
from app.services.recipe_seed_service import seed_development_recipes


def main() -> None:
    db = SessionLocal()
    try:
        result = seed_development_recipes(db)
        print(
            "Seeded development recipes: "
            f"inserted={result.inserted}, updated={result.updated}, total={result.total}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
