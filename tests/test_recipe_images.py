import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.database import SessionLocal
from app.core.exceptions import APIErrorException
from app.models.recipe import Recipe
from app.scripts import generate_recipe_images
from app.services import recipe_image_service
from app.services.recipe_image_service import build_recipe_image_prompt, generate_recipe_image
from tests.test_meal_plan_persistence import meal_plan_db
from tests.test_scheduled_meal_plans import seeded_schedule_catalog


WEBP = b"RIFF" + (12).to_bytes(4, "little") + b"WEBPVP8 test!"
IMAGE_FIELDS = (
    "image_url", "image_storage_key", "image_status", "image_prompt", "image_model", "image_generated_at",
    "image_error", "image_generation_token", "image_generation_started_at",
)


@pytest.fixture
def image_settings():
    return Settings(
        _env_file=None, openai_api_key="test-image-api-key", image_storage_bucket="test-images",
        image_storage_region="auto", image_storage_endpoint_url="https://storage.example.test",
        image_storage_public_base_url="https://images.example.test", image_storage_access_key_id="test-access",
        image_storage_secret_access_key="test-secret",
    )


@pytest.fixture
def image_boundaries(monkeypatch, image_settings):
    sdk = MagicMock()
    sdk.images.generate.return_value = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(WEBP).decode())])
    sdk_factory = MagicMock()
    sdk_factory.return_value.__enter__.return_value = sdk
    storage = MagicMock()
    storage_factory = MagicMock(return_value=storage)
    monkeypatch.setattr("openai.OpenAI", sdk_factory)
    monkeypatch.setattr("boto3.client", storage_factory)
    monkeypatch.setattr(recipe_image_service, "get_settings", lambda: image_settings)
    return SimpleNamespace(sdk=sdk, sdk_factory=sdk_factory, storage=storage, storage_factory=storage_factory)


@pytest.fixture
def image_recipe(meal_plan_db, seeded_schedule_catalog, image_boundaries):
    db, _, _ = meal_plan_db
    recipe = db.query(Recipe).filter_by(source="development_fixture", name="Banana Rice Energy Bowl", active=True).one()
    recipe_id = recipe.id
    original = {field: getattr(recipe, field) for field in IMAGE_FIELDS}
    yield db, recipe_id
    db.rollback()
    db.expire_all()
    recipe = db.get(Recipe, recipe_id)
    for field, value in original.items():
        setattr(recipe, field, value)
    db.commit()


def test_prompt_is_deterministic_and_uses_only_structured_base_recipe():
    recipe = SimpleNamespace(
        name="Rice and Banana", description="A simple fruit bowl.", servings=10,
        ingredients=[SimpleNamespace(food=SimpleNamespace(name=name)) for name in ["Rice", "Banana", "rice", "Rice"]],
        tag_links=[SimpleNamespace(tag=SimpleNamespace(name=name)) for name in ["vegan", "snack", "pre_workout"]],
    )
    prompt = build_recipe_image_prompt(recipe)
    recipe.ingredients.reverse()
    recipe.servings = 0.75
    assert build_recipe_image_prompt(recipe) == prompt
    assert all(value in prompt for value in [recipe.name, recipe.description, "Rice", "Banana", "snack", "pre_workout"])
    assert "45-degree" in prompt and "No people" in prompt and "do not invent major ingredients" in prompt
    assert "serving_amount" not in prompt and "0.75" not in prompt and "10" not in prompt


def test_generation_decodes_webp_uploads_once_and_persists_metadata(image_recipe, image_boundaries, image_settings):
    db, recipe_id = image_recipe

    def generate_outside_transaction(**kwargs):
        assert not db.in_transaction()
        with SessionLocal() as observer:
            stored = observer.get(Recipe, recipe_id)
            assert stored.image_status == "generating" and stored.image_generation_token is not None
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(WEBP).decode())])

    image_boundaries.sdk.images.generate.side_effect = generate_outside_transaction
    image_boundaries.storage.put_object.side_effect = lambda **kwargs: not db.in_transaction() or pytest.fail("Open storage transaction")
    result = generate_recipe_image(db, recipe_id)

    image_boundaries.sdk_factory.assert_called_once_with(api_key="test-image-api-key", timeout=180.0, max_retries=0)
    image_boundaries.sdk.images.generate.assert_called_once()
    arguments = image_boundaries.sdk.images.generate.call_args.kwargs
    assert {key: arguments[key] for key in ("model", "n", "size", "quality", "output_format", "output_compression", "extra_body")} == {
        "model": "gpt-image-2.6-flare", "n": 1, "size": "1024x1024", "quality": "medium", "output_format": "webp",
        "output_compression": 85, "extra_body": {"complexity": "low"},
    }
    image_boundaries.storage.put_object.assert_called_once()
    upload = image_boundaries.storage.put_object.call_args.kwargs
    assert upload == {
        "Bucket": "test-images", "Key": upload["Key"], "Body": WEBP,
        "ContentType": "image/webp", "CacheControl": "public, max-age=31536000, immutable",
    }
    assert upload["Key"].startswith(f"recipes/{recipe_id}/") and upload["Key"].endswith(".webp")
    assert result.image_url == "https://images.example.test/" + upload["Key"]
    assert result.image_status == "ready"
    db.expire_all()
    recipe = db.get(Recipe, recipe_id)
    assert recipe.image_prompt == arguments["prompt"]
    assert recipe.image_model == image_settings.openai_image_model
    assert recipe.image_generated_at.tzinfo is not None
    assert recipe.image_error is None and recipe.image_generation_token is None and recipe.image_generation_started_at is None
    assert recipe.image_storage_key == upload["Key"]


def test_cached_ready_image_does_not_need_configuration_or_external_clients(image_recipe, image_boundaries, image_settings):
    db, recipe_id = image_recipe
    original = generate_recipe_image(db, recipe_id)
    image_boundaries.sdk_factory.reset_mock()
    image_boundaries.storage_factory.reset_mock()
    image_settings.openai_api_key = ""
    image_settings.image_storage_secret_access_key = ""

    assert generate_recipe_image(db, recipe_id) == original
    image_boundaries.sdk_factory.assert_not_called()
    image_boundaries.storage_factory.assert_not_called()


def test_forced_regeneration_versions_key_and_ignores_old_object_delete_failure(image_recipe, image_boundaries):
    db, recipe_id = image_recipe
    original = generate_recipe_image(db, recipe_id)
    old_key = db.get(Recipe, recipe_id).image_storage_key
    image_boundaries.storage.delete_object.side_effect = RuntimeError("private-provider-error")

    regenerated = generate_recipe_image(db, recipe_id, force=True)

    assert regenerated.image_url != original.image_url
    assert regenerated.image_status == "ready"
    assert image_boundaries.sdk.images.generate.call_count == 2
    assert image_boundaries.storage.put_object.call_count == 2
    image_boundaries.storage.delete_object.assert_called_once_with(Bucket="test-images", Key=old_key)


@pytest.mark.parametrize("boundary", ["openai", "storage"])
@pytest.mark.parametrize("has_previous", [False, True])
def test_failure_is_sanitized_clears_claim_and_preserves_previous_ready_image(
    image_recipe, image_boundaries, boundary, has_previous,
):
    db, recipe_id = image_recipe
    if has_previous:
        generate_recipe_image(db, recipe_id)
    previous = {field: getattr(db.get(Recipe, recipe_id), field) for field in IMAGE_FIELDS}
    if boundary == "openai":
        image_boundaries.sdk.images.generate.side_effect = RuntimeError("test-image-api-key test-secret private-endpoint")
    else:
        image_boundaries.storage.put_object.side_effect = RuntimeError("test-image-api-key test-secret private-endpoint")

    with pytest.raises(APIErrorException) as failure:
        generate_recipe_image(db, recipe_id, force=True)

    assert failure.value.code == "RECIPE_IMAGE_GENERATION_FAILED"
    assert failure.value.status_code == 502
    db.expire_all()
    recipe = db.get(Recipe, recipe_id)
    assert recipe.image_status == ("ready" if has_previous else "failed")
    assert recipe.image_generation_token is None and recipe.image_generation_started_at is None
    assert recipe.image_error and len(recipe.image_error) <= 512
    assert all(value not in recipe.image_error + failure.value.message for value in ("test-image-api-key", "test-secret", "private-endpoint"))
    if has_previous:
        assert {field: getattr(recipe, field) for field in recipe_image_service.SAVED_IMAGE_FIELDS} == {
            field: previous[field] for field in recipe_image_service.SAVED_IMAGE_FIELDS
        }
    else:
        assert recipe.image_url is None and recipe.image_storage_key is None and recipe.image_generated_at is None
        assert recipe.image_prompt and recipe.image_model


@pytest.mark.parametrize("encoded", [None, "", "%%%invalid", "á", base64.b64encode(b"not-webp").decode()])
def test_missing_or_malformed_image_data_fails_without_upload(image_recipe, image_boundaries, encoded):
    db, recipe_id = image_recipe
    image_boundaries.sdk.images.generate.return_value.data = [SimpleNamespace(b64_json=encoded)]
    with pytest.raises(APIErrorException) as failure:
        generate_recipe_image(db, recipe_id)
    assert failure.value.details["reason"] == "invalid_image_data"
    image_boundaries.storage_factory.assert_not_called()
    assert db.get(Recipe, recipe_id).image_status == "failed"


def test_empty_image_response_fails_without_upload(image_recipe, image_boundaries):
    db, recipe_id = image_recipe
    image_boundaries.sdk.images.generate.return_value.data = []
    with pytest.raises(APIErrorException):
        generate_recipe_image(db, recipe_id)
    image_boundaries.storage_factory.assert_not_called()
    assert db.get(Recipe, recipe_id).image_status == "failed"


@pytest.mark.parametrize("setting", [
    "openai_api_key", "image_storage_bucket", "image_storage_region", "image_storage_public_base_url",
    "image_storage_access_key_id", "image_storage_secret_access_key",
])
def test_missing_configuration_is_controlled_before_paid_generation(image_recipe, image_boundaries, image_settings, setting):
    db, recipe_id = image_recipe
    setattr(image_settings, setting, "")
    with pytest.raises(APIErrorException) as failure:
        generate_recipe_image(db, recipe_id)
    assert failure.value.code == "RECIPE_IMAGE_CONFIGURATION_MISSING" and failure.value.status_code == 503
    assert setting.upper() in failure.value.details["settings"]
    image_boundaries.sdk_factory.assert_not_called()
    image_boundaries.storage_factory.assert_not_called()
    assert db.get(Recipe, recipe_id).image_status == "missing"


@pytest.mark.parametrize("url", [
    "https://[malformed", "https://images.example.test:invalid", "https://user:secret@images.example.test",
    "https://images.example.test?secret=private", "file:///tmp/images", "https://images.example.test/#fragment",
])
def test_invalid_public_storage_url_is_controlled_and_not_echoed(image_recipe, image_boundaries, image_settings, url):
    db, recipe_id = image_recipe
    image_settings.image_storage_public_base_url = url
    with pytest.raises(APIErrorException) as failure:
        generate_recipe_image(db, recipe_id)
    assert failure.value.code == "RECIPE_IMAGE_CONFIGURATION_MISSING"
    assert "secret" not in failure.value.message and url not in str(failure.value.details)
    image_boundaries.sdk_factory.assert_not_called()


def test_concurrent_generation_is_rejected_without_duplicate_paid_call(image_recipe, image_boundaries):
    db, recipe_id = image_recipe

    def concurrent_request(**kwargs):
        with SessionLocal() as other:
            with pytest.raises(APIErrorException) as failure:
                generate_recipe_image(other, recipe_id, force=True)
            assert failure.value.code == "RECIPE_IMAGE_GENERATION_IN_PROGRESS"
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(WEBP).decode())])

    image_boundaries.sdk.images.generate.side_effect = concurrent_request
    assert generate_recipe_image(db, recipe_id).image_status == "ready"
    assert image_boundaries.sdk.images.generate.call_count == 1


def test_expired_generation_claim_can_be_recovered(image_recipe):
    db, recipe_id = image_recipe
    recipe = db.get(Recipe, recipe_id)
    recipe.image_status = "generating"
    recipe.image_generation_token = uuid4()
    recipe.image_generation_started_at = datetime.now(UTC) - timedelta(hours=1)
    db.commit()
    assert generate_recipe_image(db, recipe_id).image_status == "ready"


def test_superseded_worker_cannot_overwrite_newer_image(image_recipe, image_boundaries):
    db, recipe_id = image_recipe
    newer_url = "https://images.example.test/newer.webp"

    def finish_newer_generation(**kwargs):
        with SessionLocal.begin() as other:
            recipe = other.get(Recipe, recipe_id)
            recipe.image_generation_token = None
            recipe.image_status = "ready"
            recipe.image_url = newer_url
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(WEBP).decode())])

    image_boundaries.sdk.images.generate.side_effect = finish_newer_generation
    with pytest.raises(APIErrorException) as failure:
        generate_recipe_image(db, recipe_id)
    assert failure.value.code == "RECIPE_IMAGE_GENERATION_SUPERSEDED"
    db.expire_all()
    assert db.get(Recipe, recipe_id).image_url == newer_url
    assert db.get(Recipe, recipe_id).image_status == "ready"
    image_boundaries.storage.delete_object.assert_called_once()


def test_database_save_failure_cleans_uploaded_object_and_clears_claim(image_recipe, image_boundaries, monkeypatch):
    db, recipe_id = image_recipe
    commit = db.commit
    calls = 0

    def fail_success_commit_once():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SQLAlchemyError("test-secret")
        commit()

    monkeypatch.setattr(db, "commit", fail_success_commit_once)
    with pytest.raises(APIErrorException) as failure:
        generate_recipe_image(db, recipe_id)
    assert "test-secret" not in failure.value.message
    db.expire_all()
    assert db.get(Recipe, recipe_id).image_status == "failed"
    assert db.get(Recipe, recipe_id).image_generation_token is None
    image_boundaries.storage.delete_object.assert_called_once()


@pytest.mark.parametrize("has_previous", [False, True])
def test_lost_commit_acknowledgment_preserves_the_successfully_saved_image(
    image_recipe, image_boundaries, monkeypatch, has_previous,
):
    db, recipe_id = image_recipe
    if has_previous:
        generate_recipe_image(db, recipe_id)
    commit = db.commit
    calls = 0

    def lose_success_acknowledgment_once():
        nonlocal calls
        calls += 1
        commit()
        if calls == 2:
            raise SQLAlchemyError("Simulated connection loss after a committed write")

    monkeypatch.setattr(db, "commit", lose_success_acknowledgment_once)

    result = generate_recipe_image(db, recipe_id, force=True)

    assert result.image_status == "ready"
    db.expire_all()
    recipe = db.get(Recipe, recipe_id)
    assert recipe.image_storage_key == image_boundaries.storage.put_object.call_args.kwargs["Key"]
    assert recipe.image_url == result.image_url
    assert recipe.image_generation_token is None and recipe.image_error is None
    image_boundaries.storage.delete_object.assert_not_called()


def test_normal_aws_storage_does_not_require_endpoint_override(image_recipe, image_boundaries, image_settings):
    db, recipe_id = image_recipe
    image_settings.image_storage_endpoint_url = ""
    image_settings.image_storage_region = "us-east-1"
    generate_recipe_image(db, recipe_id)
    assert image_boundaries.storage_factory.call_args.kwargs["endpoint_url"] is None
    assert image_boundaries.storage_factory.call_args.kwargs["region_name"] == "us-east-1"


def test_batch_skips_ready_and_supports_forced_regeneration(image_recipe, image_boundaries, capsys):
    db, recipe_id = image_recipe
    generate_recipe_image(db, recipe_id)
    image_boundaries.sdk.images.generate.reset_mock()
    assert generate_recipe_images.main(["--recipe-id", str(recipe_id), "--limit", "1"]) == 0
    assert "ready=1, skipped=1, generated=0, failed=0, total=1" in capsys.readouterr().out
    image_boundaries.sdk.images.generate.assert_not_called()
    assert generate_recipe_images.main(["--force", "--recipe-id", str(recipe_id)]) == 0
    assert "ready=1, skipped=0, generated=1, failed=0, total=1" in capsys.readouterr().out
    image_boundaries.sdk.images.generate.assert_called_once()


def test_batch_continues_after_failure_and_prints_safe_summary(image_recipe, monkeypatch, capsys):
    calls = []

    def fail_first(db, recipe_id, **kwargs):
        calls.append(recipe_id)
        if len(calls) == 1:
            raise RuntimeError("test-secret")

    monkeypatch.setattr(generate_recipe_images, "generate_recipe_image", fail_first)
    assert generate_recipe_images.main(["--limit", "3"]) == 1
    output = capsys.readouterr().out
    assert len(calls) == 3 and "test-secret" not in output
    assert "ready=2, skipped=0, generated=2, failed=1, total=3" in output
