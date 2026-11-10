"""Explicit image-generation boundary; never used by planning or read requests."""
import base64
import binascii

from app.core.config import Settings


MAX_IMAGE_BYTES = 20 * 1024 * 1024


class RecipeImageProviderError(Exception):
    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


class OpenAIRecipeImageClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def generate(self, prompt: str) -> bytes:
        from openai import OpenAI, APITimeoutError, AuthenticationError, RateLimitError

        try:
            # Disable automatic retries: retrying a timed-out paid generation
            # could produce and bill for another image.
            with OpenAI(
                api_key=self.settings.openai_api_key,
                timeout=self.settings.openai_image_timeout_seconds,
                max_retries=0,
            ) as client:
                result = client.images.generate(
                    model=self.settings.openai_image_model,
                    prompt=prompt,
                    n=1,
                    size=self.settings.openai_image_size,
                    quality=self.settings.openai_image_quality,
                    output_format="webp",
                    output_compression=85,
                    # The pinned SDK predates the named complexity argument.
                    extra_body={"complexity": self.settings.openai_image_complexity},
                )
        except APITimeoutError:
            raise RecipeImageProviderError("timeout") from None
        except AuthenticationError:
            raise RecipeImageProviderError("authentication") from None
        except RateLimitError:
            raise RecipeImageProviderError("rate_limit") from None
        except Exception:
            raise RecipeImageProviderError("request_failed") from None

        data = getattr(result, "data", None)
        encoded = getattr(data[0], "b64_json", None) if data else None
        if not isinstance(encoded, str) or not encoded or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise RecipeImageProviderError("invalid_image_data")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise RecipeImageProviderError("invalid_image_data") from None
        if (len(content) < 12 or len(content) > MAX_IMAGE_BYTES
                or content[:4] != b"RIFF" or content[8:12] != b"WEBP"):
            raise RecipeImageProviderError("invalid_image_data")
        return content
