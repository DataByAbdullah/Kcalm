from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class RecipeImageGenerateRequest(BaseModel):
    force: bool = False


class RecipeImageResponse(BaseModel):
    recipe_id: UUID
    image_url: str | None
    image_status: Literal["missing", "generating", "ready", "failed"]
    image_model: str | None
    image_generated_at: datetime | None
