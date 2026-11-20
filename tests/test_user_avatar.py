import base64
import binascii
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
import struct
from types import SimpleNamespace
from uuid import UUID

import jwt
from PIL import Image, PngImagePlugin
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.database import SessionLocal, get_db
from app.main import app
from app.models.rate_limit import RateLimitBucket
from app.models.user import User
from app.services import avatar_service
from app.services.user_profile_service import get_profile
from tests.test_auth import auth_db, login_user
from tests.test_meal_plan_persistence import create_profile, register_and_login, unique_email
from tests.test_weight_logs import request, tracking_user


PATH = "/users/me/avatar"


def image_bytes(format="PNG", color="blue", **options):
    output = BytesIO()
    Image.new("RGB", (16, 16), color).save(output, format=format, **options)
    return output.getvalue()


def data_url(content, mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")


def upload(token, image):
    return request("PUT", PATH, token, {"image": image})


def assert_error(response, code="INVALID_AVATAR"):
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"] == {}


def test_default_null_avatar_is_additive_and_internal_column_is_private(tracking_user):
    db, token = tracking_user
    response = request("GET", "/auth/me", token)
    assert response.status_code == 200
    assert response.json()["avatar"] is None
    assert set(response.json()) == {"id", "email", "full_name", "membership_tier", "is_active", "is_admin", "avatar"}
    assert request("GET", "/users/profile", token).status_code == 404
    create_profile(token)
    profile = request("GET", "/users/profile", token)
    assert profile.status_code == 200 and profile.json()["avatar"] is None
    assert profile.json()["age"] == 29 and profile.json()["meals_per_day"] == 4
    assert db.get(User, UUID(response.json()["id"])).avatar_data_url is None
    assert "avatar_data_url" not in response.text + profile.text


@pytest.mark.parametrize("format,mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_upload_persistence_visibility_and_backward_compatibility(tracking_user, format, mime):
    db, token = tracking_user
    before = request("GET", "/auth/me", token).json()
    image = data_url(image_bytes(format), mime)
    response = upload(token, image)
    assert response.status_code == 200, response.text
    assert response.json() == {**before, "avatar": image}
    assert response.headers["Cache-Control"] == "no-store"
    assert request("GET", "/auth/me", token).json() == response.json()
    db.expire_all()
    assert db.get(User, UUID(before["id"])).avatar_data_url == image
    create_profile(token)
    profile = request("GET", "/users/profile", token).json()
    assert profile["avatar"] == image and profile["age"] == 29
    patched = request("PATCH", "/users/profile", token, {"target_weight_kg": 75})
    assert patched.status_code == 200 and patched.json()["avatar"] == image
    renamed = request("PATCH", "/users/me", token, {"full_name": " Avatar User "})
    assert renamed.status_code == 200 and renamed.json()["full_name"] == "Avatar User"
    assert renamed.json()["avatar"] == image
    assert "avatar_data_url" not in response.text + renamed.text


def test_replacement_updates_same_user_and_only_avatar(tracking_user):
    db, token = tracking_user
    before = request("GET", "/auth/me", token).json()
    assert upload(token, data_url(image_bytes(color="red"))).status_code == 200
    image = data_url(image_bytes("WEBP", color="green"), "image/webp")
    response = upload(token, image)
    assert response.status_code == 200 and response.json() == {**before, "avatar": image}
    db.expire_all()
    assert db.query(User).filter_by(id=UUID(before["id"])).count() == 1
    assert db.get(User, UUID(before["id"])).avatar_data_url == image


def test_deletion_is_idempotent_and_clears_all_responses(tracking_user):
    db, token = tracking_user
    create_profile(token)
    assert upload(token, data_url(image_bytes())).status_code == 200
    for _ in range(2):
        response = request("DELETE", PATH, token)
        assert response.status_code == 204 and response.content == b""
        assert request("GET", "/auth/me", token).json()["avatar"] is None
        assert request("GET", "/users/profile", token).json()["avatar"] is None
    db.expire_all()
    user_id = UUID(request("GET", "/auth/me", token).json()["id"])
    assert db.get(User, user_id).avatar_data_url is None


def test_header_is_canonicalized(tracking_user):
    _, token = tracking_user
    image = data_url(image_bytes())
    response = upload(token, image.replace("data:image/png;base64,", "DATA:IMAGE/PNG;BASE64,"))
    assert response.status_code == 200 and response.json()["avatar"] == image


@pytest.mark.parametrize("options,chunk", [
    ({"lossless": True}, b"VP8L"),
    ({"exif": b"Exif\x00\x00II\x2a\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00"}, b"VP8X"),
], ids=["lossless", "extended"])
def test_lossless_and_extended_static_webp_are_supported(tracking_user, options, chunk):
    _, token = tracking_user
    content = image_bytes("WEBP", **options)
    assert content[12:16] == chunk
    image = data_url(content, "image/webp")
    response = upload(token, image)
    assert response.status_code == 200, response.text
    assert response.json()["avatar"] == image


@pytest.mark.parametrize("image", [
    "", "https://example.com/avatar.png", "data:image/png;base64,",
    "data:image/png;base64,%%%", "data:image/png;base64,AA", "data:image/png;base64,AA===",
    "data:image/png;base64,AB==", "data:image/png;base64,\u2603", "data:image/png;base64,AAAA\n",
    "data:image/png;charset=utf-8;base64,AAAA", "data:image/png,AAAA",
    "data:image/gif;base64,R0lGODlh", "data:image/svg+xml;base64,PHN2Zy8+",
    "data:text/html;base64,PGgxPnRlc3Q8L2gxPg==", "data:application/octet-stream;base64,AAAA",
], ids=["empty", "external-url", "empty-base64", "alphabet", "missing-padding", "extra-padding",
        "pad-bits", "unicode", "whitespace", "mime-parameter", "not-base64", "gif", "svg", "html", "binary"])
def test_invalid_urls_do_not_mutate_or_log_images(tracking_user, image, caplog):
    _, token = tracking_user
    previous = data_url(image_bytes(color="red"))
    assert upload(token, previous).status_code == 200
    response = upload(token, image)
    assert_error(response)
    assert request("GET", "/auth/me", token).json()["avatar"] == previous
    if image:
        assert image not in response.text + caplog.text


@pytest.mark.parametrize("body", [{}, {"image": None}, {"image": 5}, {"image": []}, {"image": {}}, [], "image"])
def test_invalid_request_shapes_use_sanitized_avatar_error(tracking_user, body):
    assert_error(request("PUT", PATH, tracking_user[1], body))


def test_malformed_json_is_sanitized(tracking_user):
    from tests.test_auth import api_request, run_async
    response = run_async(api_request("PUT", "/api/v1" + PATH,
        headers={"Authorization": "Bearer " + tracking_user[1], "Content-Type": "application/json"},
        content=b'{"image":"private-invalid-json'))
    assert_error(response)
    assert "private-invalid-json" not in response.text


@pytest.mark.parametrize("format,mime", [("JPEG", "image/png"), ("PNG", "image/webp"), ("WEBP", "image/jpeg"), ("GIF", "image/png")])
def test_mime_must_match_actual_content(tracking_user, format, mime):
    assert_error(upload(tracking_user[1], data_url(image_bytes(format), mime)))


@pytest.mark.parametrize("content,mime", [
    (b"not an image", "image/jpeg"), (b"\x89PNG\r\n\x1a\nnot PNG", "image/png"),
    (b"\xff\xd8\xfftruncated", "image/jpeg"), (b"RIFF\x00\x00\x00\x00WEBPbroken", "image/webp"),
    (image_bytes("JPEG")[:-20], "image/jpeg"), (image_bytes("PNG")[:-20], "image/png"),
    (image_bytes("WEBP")[:-10], "image/webp"),
], ids=["non-image", "png-header", "jpeg-header", "webp-header", "truncated-jpeg", "truncated-png", "truncated-webp"])
def test_corrupt_and_truncated_images(tracking_user, content, mime):
    assert_error(upload(tracking_user[1], data_url(content, mime)))


def test_png_crc_corruption_is_rejected(tracking_user):
    content = bytearray(image_bytes())
    content[29] ^= 1
    assert_error(upload(tracking_user[1], data_url(content)))


@pytest.mark.parametrize("format,mime", [("PNG", "image/png"), ("WEBP", "image/webp")])
def test_animation_is_rejected(tracking_user, format, mime):
    output = BytesIO()
    Image.new("RGB", (16, 16), "red").save(output, format=format, save_all=True,
        append_images=[Image.new("RGB", (16, 16), "blue")], duration=100, loop=0)
    assert_error(upload(tracking_user[1], data_url(output.getvalue(), mime)))


def test_exact_byte_limit_accepted_and_one_byte_over_rejected(tracking_user):
    def padded_png(size):
        info = PngImagePlugin.PngInfo()
        info.add_text("padding", "x")
        overhead = len(image_bytes(pnginfo=info)) - 1
        info = PngImagePlugin.PngInfo()
        info.add_text("padding", "x" * (size - overhead))
        content = image_bytes(pnginfo=info)
        assert len(content) == size
        return content
    token = tracking_user[1]
    image = data_url(padded_png(307200))
    assert upload(token, image).status_code == 200
    assert_error(upload(token, data_url(padded_png(307201))), "AVATAR_TOO_LARGE")
    assert request("GET", "/auth/me", token).json()["avatar"] == image


def test_encoded_size_is_checked_before_decoding(tracking_user, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Oversized input must not be decoded")
    monkeypatch.setattr(avatar_service, "base64", SimpleNamespace(b64decode=forbidden, b64encode=forbidden))
    assert_error(upload(tracking_user[1], "data:image/png;base64," + "A" * 409604), "AVATAR_TOO_LARGE")


@pytest.mark.parametrize("width,height", [(4097, 1), (2049, 2049), (10000, 10000), (20000, 20000)])
def test_pixel_limits_and_decompression_bombs(tracking_user, width, height, caplog):
    original = image_bytes()
    ihdr = struct.pack(">II", width, height) + original[24:29]
    content = original[:16] + ihdr + struct.pack(">I", binascii.crc32(b"IHDR" + ihdr)) + original[33:]
    response = upload(tracking_user[1], data_url(content))
    assert_error(response, "AVATAR_TOO_LARGE")
    assert "DecompressionBomb" not in response.text + caplog.text


@pytest.mark.parametrize("chunk", [b"VP8 ", b"VP8L", b"VP8X"], ids=["lossy", "lossless", "extended"])
def test_webp_size_checked_before_decoder_allocation(tracking_user, monkeypatch, chunk):
    width = height = 6000
    if chunk == b"VP8 ":
        payload = b"\x10\x00\x00\x9d\x01\x2a" + struct.pack("<HH", width, height)
    elif chunk == b"VP8L":
        payload = b"\x2f" + struct.pack("<I", (width - 1) | ((height - 1) << 14))
    else:
        payload = b"\x00" * 4 + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    body = b"WEBP" + chunk + struct.pack("<I", len(payload)) + payload + b"\x00" * (len(payload) % 2)
    content = b"RIFF" + struct.pack("<I", len(body)) + body
    def forbidden(*args, **kwargs):
        pytest.fail("Oversized WebP must not reach Image.open")
    monkeypatch.setattr(avatar_service.Image, "open", forbidden)
    assert_error(upload(tracking_user[1], data_url(content, "image/webp")), "AVATAR_TOO_LARGE")


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_authentication_required(method):
    response = request(method, PATH, body={"image": data_url(image_bytes())} if method == "PUT" else None)
    assert response.status_code == 401 and response.json()["error"]["code"] == "INVALID_TOKEN"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_cross_user_isolation(tracking_user, auth_db):
    token = tracking_user[1]
    other = register_and_login(auth_db[1](unique_email("avatar-other")))
    other_id = request("GET", "/auth/me", other).json()["id"]
    other_image = data_url(image_bytes(color="red"))
    assert upload(other, other_image).status_code == 200
    image = data_url(image_bytes())
    assert_error(request("PUT", PATH, token, {"image": image, "user_id": other_id}))
    assert request("PUT", f"/users/{other_id}/avatar", token, {"image": image}).status_code == 404
    own = request("PUT", PATH + "?user_id=" + other_id, token, {"image": image})
    assert own.status_code == 200 and own.json()["avatar"] == image
    assert request("DELETE", PATH + "?user_id=" + other_id, token).status_code == 204
    assert request("GET", "/auth/me", other).json()["avatar"] == other_image
    assert request("GET", "/auth/me", token).json()["avatar"] is None


def test_shared_quota_per_user_and_expiration(tracking_user, auth_db):
    db, token = tracking_user
    image = data_url(image_bytes())
    for index in range(10):
        response = upload(token, image) if index % 2 == 0 else request("DELETE", PATH, token)
        assert response.status_code == (200 if index % 2 == 0 else 204)
    for response in (upload(token, image), request("DELETE", PATH, token)):
        assert response.status_code == 429 and response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert request("GET", "/auth/me", token).json()["avatar"] is None
    other = register_and_login(auth_db[1](unique_email("avatar-limit-other")))
    assert upload(other, image).status_code == 200
    buckets = db.scalars(select(RateLimitBucket).where(RateLimitBucket.request_count == 10)).all()
    assert len(buckets) == 1
    buckets[0].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert upload(token, image).status_code == 200


def test_invalid_images_consume_quota(tracking_user):
    for _ in range(10):
        assert_error(upload(tracking_user[1], "not an image"))
    assert request("DELETE", PATH, tracking_user[1]).status_code == 429


def test_concurrent_mutations_cannot_bypass_shared_limit(tracking_user):
    token = tracking_user[1]
    image = data_url(image_bytes())
    def attempt(index):
        return upload(token, image) if index % 2 == 0 else request("DELETE", PATH, token)
    with ThreadPoolExecutor(max_workers=6) as workers:
        results = list(workers.map(attempt, range(12)))
    assert sum(r.status_code in {200, 204} for r in results) == 10
    assert sum(r.status_code == 429 for r in results) == 2
    assert all(r.status_code in {200, 204, 429} for r in results)


def test_export_includes_avatar_and_account_deletion_removes_it(tracking_user, auth_db):
    response = upload(tracking_user[1], data_url(image_bytes()))
    assert response.status_code == 200
    token, image, user_id = tracking_user[1], response.json()["avatar"], UUID(response.json()["id"])
    export = request("GET", "/users/me/export", token)
    assert export.status_code == 200 and export.json()["user"]["avatar"] == image
    assert export.headers["Cache-Control"] == "no-store" and "avatar_data_url" not in export.text
    other = register_and_login(auth_db[1](unique_email("avatar-export-other")))
    assert request("GET", "/users/me/export", other).json()["user"]["avatar"] is None
    assert request("DELETE", "/users/me", token).status_code == 204
    with SessionLocal() as fresh:
        assert fresh.get(User, user_id) is None
    assert request("GET", "/auth/me", token).status_code == 401
    assert request("GET", "/auth/me", other).status_code == 200


def test_new_jwt_claims_never_contain_avatar(tracking_user):
    response = upload(tracking_user[1], data_url(image_bytes()))
    assert response.status_code == 200
    tokens = login_user(response.json()["email"]).json()
    for name in ("access_token", "refresh_token"):
        claims = jwt.decode(tokens[name], options={"verify_signature": False})
        assert set(claims) == {"sub", "type", "ver", "iat", "exp"}
        assert response.json()["avatar"] not in str(claims)
    assert request("GET", "/auth/me", tracking_user[1]).status_code == 200


def test_unrelated_queries_and_internal_planning_profile_do_not_load_avatar(tracking_user):
    create_profile(tracking_user[1])
    response = upload(tracking_user[1], data_url(image_bytes()))
    assert response.status_code == 200
    with SessionLocal() as db:
        user = db.get(User, UUID(response.json()["id"]))
        assert "avatar_data_url" in inspect(user).unloaded
        profile = get_profile(db, user)
        assert "avatar_data_url" in inspect(user).unloaded
        assert "avatar" not in profile.model_dump()


def test_avatar_does_not_invalidate_plans_or_change_planning_inputs(tracking_user, monkeypatch):
    from app.services import user_profile_service
    from app.services.meal_plan_service import ensure_profile_unchanged
    db, token = tracking_user
    create_profile(token)
    user = db.get(User, UUID(request("GET", "/auth/me", token).json()["id"]))
    before = get_profile(db, user)
    def forbidden(*args, **kwargs):
        pytest.fail("Avatar mutation must not invalidate meal plans")
    monkeypatch.setattr(user_profile_service, "invalidate_future_meal_plans", forbidden)
    assert upload(token, data_url(image_bytes())).status_code == 200
    assert get_profile(db, user) == before
    ensure_profile_unchanged(db, user, before)
    assert request("DELETE", PATH, token).status_code == 204
    assert get_profile(db, user) == before


def test_database_failure_rolls_back_without_leaking_image(tracking_user, monkeypatch, caplog):
    db, token = tracking_user
    previous, replacement = data_url(image_bytes()), data_url(image_bytes(color="red"))
    assert upload(token, previous).status_code == 200
    app.dependency_overrides[get_db] = lambda: db
    try:
        with monkeypatch.context() as patch:
            def fail_commit():
                raise SQLAlchemyError("private database details " + replacement)
            patch.setattr(db, "commit", fail_commit)
            response = upload(token, replacement)
        assert response.status_code == 500 and response.json()["error"]["code"] == "AVATAR_UPDATE_FAILED"
        assert replacement not in response.text + caplog.text
        assert "private database details" not in response.text + caplog.text
        assert request("GET", "/auth/me", token).json()["avatar"] == previous
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_limiter_failure_fails_closed(tracking_user, monkeypatch):
    def unavailable():
        raise SQLAlchemyError("private limiter details")
    monkeypatch.setattr("app.core.rate_limits.SessionLocal.begin", unavailable)
    response = upload(tracking_user[1], data_url(image_bytes()))
    assert response.status_code == 503 and response.json()["error"]["code"] == "RATE_LIMIT_UNAVAILABLE"
    assert "private limiter" not in response.text
    assert request("GET", "/auth/me", tracking_user[1]).json()["avatar"] is None


def test_other_account_endpoints_cannot_bypass_avatar_validation(tracking_user, auth_db):
    token = tracking_user[1]
    create_profile(token)
    image = data_url(image_bytes())
    assert upload(token, image).status_code == 200
    forged = {"avatar_data_url": "unvalidated", "avatar": "unvalidated"}
    renamed = request("PATCH", "/users/me", token, {"full_name": "Still Me", **forged})
    assert renamed.status_code == 200 and renamed.json()["avatar"] == image
    profile = request("PATCH", "/users/profile", token, forged)
    assert profile.status_code == 200 and profile.json()["avatar"] == image
    new_user = request("POST", "/auth/register", body={
        "email": auth_db[1](unique_email("avatar-mass-assignment")), "password": "StrongPassword123", **forged})
    assert new_user.status_code == 201 and new_user.json()["avatar"] is None


def test_avatar_rate_limit_defaults():
    settings = Settings(_env_file=None)
    assert settings.rate_limit_avatar_requests == 10
    assert settings.rate_limit_avatar_window_seconds == 60
