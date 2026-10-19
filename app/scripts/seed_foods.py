from app.core.database import SessionLocal
from app.services.food_seed_service import seed_development_foods


def main() -> None:
    db = SessionLocal()
    try:
        result = seed_development_foods(db)
    finally:
        db.close()

    print(
        f"Seeded development foods: inserted={result.inserted}, "
        f"updated={result.updated}, total={result.total}"
    )


if __name__ == "__main__":
    main()
