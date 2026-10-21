"""Operator-only import of reviewed food allergen metadata, never inferred from names."""
import argparse
from uuid import UUID

from app.core.database import SessionLocal
from app.services.food_service import get_food_detail
from app.services.dietary_service import ALLERGEN_CODES, review_food_allergens


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--food-id", required=True, type=UUID)
    parser.add_argument("--allergens", nargs="*", choices=sorted(ALLERGEN_CODES), default=[])
    parser.add_argument("--reference", required=True)
    args = parser.parse_args()
    with SessionLocal() as db:
        food = get_food_detail(db, args.food_id)
        review_food_allergens(db, food, args.allergens, args.reference)


if __name__ == "__main__":
    main()
