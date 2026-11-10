"""Run explicitly after configuring OpenAI and S3-compatible image storage."""
import argparse
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.core.database import SessionLocal
from app.core.exceptions import APIErrorException
from app.models.recipe import Recipe
from app.services.recipe_image_service import generate_recipe_image, valid_image_url


@dataclass
class ImageBatchSummary:
    ready: int = 0
    skipped: int = 0
    generated: int = 0
    failed: int = 0
    total: int = 0


def generate_images(*, force: bool = False, recipe_id: UUID | None = None, limit: int | None = None) -> ImageBatchSummary:
    # Materialize IDs and close this read transaction before any paid requests.
    with SessionLocal() as db:
        query = db.query(Recipe.id, Recipe.image_status, Recipe.image_url).filter(Recipe.active.is_(True))
        if recipe_id is not None:
            query = query.filter(Recipe.id == recipe_id)
        query = query.order_by(Recipe.name, Recipe.id)
        if limit is not None:
            query = query.limit(limit)
        recipes = query.all()

    summary = ImageBatchSummary(total=len(recipes))
    for index, (current_id, status, url) in enumerate(recipes, 1):
        if not force and status == "ready" and valid_image_url(url):
            summary.ready += 1
            summary.skipped += 1
            print(f"[{index}/{summary.total}] {current_id}: skipped", flush=True)
            continue
        with SessionLocal() as db:
            try:
                generate_recipe_image(db, current_id, force=force)
                summary.generated += 1
                summary.ready += 1
                print(f"[{index}/{summary.total}] {current_id}: generated", flush=True)
            except Exception as exc:
                db.rollback()
                summary.failed += 1
                # Only a controlled code is printed, never provider exceptions
                # that may contain credentials or signed storage URLs.
                code = exc.code if isinstance(exc, APIErrorException) else "RECIPE_IMAGE_GENERATION_FAILED"
                print(f"[{index}/{summary.total}] {current_id}: failed ({code})", flush=True)
                try:
                    current = db.get(Recipe, current_id)
                    if current is not None and current.image_status == "ready" and valid_image_url(current.image_url):
                        summary.ready += 1
                except SQLAlchemyError:
                    db.rollback()
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate reusable Kcalm recipe images explicitly.")
    parser.add_argument("--force", action="store_true", help="Regenerate images, including ready recipes.")
    parser.add_argument("--recipe-id", type=UUID, help="Process only this active recipe.")
    parser.add_argument("--limit", type=int, help="Limit the number of active recipes processed.")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    summary = generate_images(force=args.force, recipe_id=args.recipe_id, limit=args.limit)
    print(
        f"Recipe images: ready={summary.ready}, skipped={summary.skipped}, "
        f"generated={summary.generated}, failed={summary.failed}, total={summary.total}",
        flush=True,
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
