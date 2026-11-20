from pydantic import BaseModel, ConfigDict, Field


class AvatarUploadRequest(BaseModel):
    image: str = Field(strict=True)

    model_config = ConfigDict(extra="forbid")
