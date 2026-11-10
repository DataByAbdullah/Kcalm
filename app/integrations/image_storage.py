from contextlib import closing
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.core.config import Settings


class RecipeImageStorageError(Exception):
    pass


@dataclass(frozen=True)
class StoredRecipeImage:
    key: str
    url: str


class S3RecipeImageStorage:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        import boto3
        from botocore.config import Config

        return boto3.client(
            "s3",
            region_name=self.settings.image_storage_region,
            endpoint_url=self.settings.image_storage_endpoint_url or None,
            aws_access_key_id=self.settings.image_storage_access_key_id,
            aws_secret_access_key=self.settings.image_storage_secret_access_key,
            config=Config(
                signature_version="s3v4", connect_timeout=5, read_timeout=30,
                retries={"mode": "standard", "total_max_attempts": 2},
            ),
        )

    def upload(self, recipe_id: UUID, content: bytes) -> StoredRecipeImage:
        key = f"recipes/{recipe_id}/{uuid4().hex}.webp"
        try:
            with closing(self._client()) as client:
                client.put_object(
                    Bucket=self.settings.image_storage_bucket,
                    Key=key,
                    Body=content,
                    ContentType="image/webp",
                    CacheControl="public, max-age=31536000, immutable",
                )
        except Exception:
            raise RecipeImageStorageError() from None
        return StoredRecipeImage(
            key=key, url=f"{self.settings.image_storage_public_base_url.rstrip('/')}/{key}",
        )

    def delete(self, key: str) -> None:
        with closing(self._client()) as client:
            client.delete_object(Bucket=self.settings.image_storage_bucket, Key=key)
