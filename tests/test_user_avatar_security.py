import asyncio
import binascii
import json
import struct
import zlib

from httpx import Response
from PIL import Image, PngImagePlugin
import pytest

from app.api import avatar_request
from app.main import app
from app.core.database import engine
from app.services import avatar_service
from tests.test_auth import auth_db, run_async
from tests.test_user_avatar import assert_error, data_url, image_bytes, tracking_user, upload
from tests.test_weight_logs import request


PATH = "/api/v1/users/me/avatar"


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data))


def png_with_metadata(chunks, after_idat=False):
    original = image_bytes()
    offset = len(original) - 12 if after_idat else 33
    return original[:offset] + b"".join(png_chunk(*chunk) for chunk in chunks) + original[offset:]


def compressed_metadata(kind, text):
    prefix = b"comment\0\x01\0en\0Comment\0" if kind == b"iTXt" else b"comment\0\0"
    return kind, prefix + zlib.compress(text)


@pytest.mark.parametrize("kind", [b"zTXt", b"iTXt", b"iCCP"])
@pytest.mark.parametrize("after_idat", [False, True])
def test_compressed_metadata_rejected_before_pillow(tracking_user, monkeypatch, kind, after_idat):
    content = png_with_metadata([compressed_metadata(kind, b"A" * (avatar_service.MAX_AVATAR_METADATA_BYTES + 1))], after_idat)
    assert len(content) < avatar_service.MAX_AVATAR_BYTES
    def forbidden(*args, **kwargs):
        pytest.fail("Metadata expansion must be rejected before Image.open")
    monkeypatch.setattr(avatar_service.Image, "open", forbidden)
    assert_error(upload(tracking_user[1], data_url(content)), "AVATAR_TOO_LARGE")


@pytest.mark.parametrize("kind", [b"zTXt", b"iTXt", b"iCCP"])
def test_duplicate_metadata_keys_still_consume_cumulative_budget(tracking_user, monkeypatch, kind):
    chunk = compressed_metadata(kind, b"A" * (avatar_service.MAX_AVATAR_METADATA_BYTES // 3))
    content = png_with_metadata([chunk] * 3)
    monkeypatch.setattr(avatar_service.Image, "open", lambda *a, **k: pytest.fail("Cumulative budget bypass"))
    assert_error(upload(tracking_user[1], data_url(content)), "AVATAR_TOO_LARGE")


def test_uncompressed_and_compressed_metadata_share_budget(tracking_user):
    half = avatar_service.MAX_AVATAR_METADATA_BYTES // 2
    content = png_with_metadata([(b"tEXt", b"plain\0" + b"A" * half), compressed_metadata(b"zTXt", b"A" * half)])
    assert len(content) < avatar_service.MAX_AVATAR_BYTES
    assert_error(upload(tracking_user[1], data_url(content)), "AVATAR_TOO_LARGE")


def test_original_sixty_megabyte_metadata_payload_rejected(tracking_user):
    chunk = compressed_metadata(b"zTXt", b"A" * (1024 * 1024))
    content = png_with_metadata([chunk] * 60)
    assert len(content) < avatar_service.MAX_AVATAR_BYTES
    assert_error(upload(tracking_user[1], data_url(content)), "AVATAR_TOO_LARGE")


def test_metadata_budget_boundary_and_normal_metadata(tracking_user):
    budget = avatar_service.MAX_AVATAR_METADATA_BYTES
    prefix = b"comment\0\0"
    exact = png_with_metadata([(b"zTXt", prefix + zlib.compress(b"A" * (budget - len(prefix))))])
    assert upload(tracking_user[1], data_url(exact)).status_code == 200
    too_large = png_with_metadata([(b"zTXt", prefix + zlib.compress(b"A" * (budget - len(prefix) + 1)))])
    assert_error(upload(tracking_user[1], data_url(too_large)), "AVATAR_TOO_LARGE")
    normal = png_with_metadata([
        (b"tEXt", b"Author\0Kcalm"), compressed_metadata(b"zTXt", b"A normal comment"),
        compressed_metadata(b"iTXt", "A normal Unicode comment: \u2603".encode()),
        (b"iTXt", b"Title\0\0\0en\0Title\0Plain Unicode \xe2\x98\x83"),
    ], after_idat=True)
    response = upload(tracking_user[1], data_url(normal))
    assert response.status_code == 200 and response.json()["avatar"] == data_url(normal)


@pytest.mark.parametrize("kind,data", [
    (b"zTXt", b"comment\0\0" + zlib.compress(b"text")[:-1]),
    (b"zTXt", b"comment\0\0" + zlib.compress(b"text") + b"trailing"),
    (b"zTXt", b"comment\0\0" + zlib.compress(b"one") + zlib.compress(b"two")),
    (b"zTXt", b"comment\0\0bad zlib"),
    (b"zTXt", b"comment\0\1" + zlib.compress(b"text")),
    (b"zTXt", b"\0\0" + zlib.compress(b"text")),
    (b"iCCP", b"profile\0\0" + zlib.compress(b"profile")[:-2]),
    (b"iTXt", b"comment\0\2\0en\0title\0" + zlib.compress(b"text")),
    (b"iTXt", b"comment\0\1\1en\0title\0" + zlib.compress(b"text")),
    (b"iTXt", b"comment\0\1\0missing separators"),
    (b"iTXt", b"comment\0\1\0en\0title\0" + zlib.compress(b"\xff")),
    (b"iTXt", b"comment\0\1\0\xff\0title\0" + zlib.compress(b"text")),
], ids=["truncated", "trailing", "concatenated", "bad-zlib", "method", "keyword", "icc-truncated",
        "itxt-flag", "itxt-method", "itxt-separators", "itxt-text", "itxt-language"])
def test_malformed_metadata_is_rejected_safely(tracking_user, kind, data, caplog):
    response = upload(tracking_user[1], data_url(png_with_metadata([(kind, data)], after_idat=True)))
    assert_error(response)
    assert "zlib" not in response.text + caplog.text


def test_truncated_metadata_chunk_and_bad_crc(tracking_user):
    content = png_with_metadata([compressed_metadata(b"zTXt", b"normal")])
    broken_crc = bytearray(content)
    broken_crc[50] ^= 1
    assert_error(upload(tracking_user[1], data_url(broken_crc)))
    assert_error(upload(tracking_user[1], data_url(content[:-14])))


def test_zlib_output_is_bounded_before_pillow(tracking_user, monkeypatch):
    real_factory = zlib.decompressobj
    maximums = []
    class Decoder:
        def __init__(self):
            self.decoder = real_factory()
        def decompress(self, data, max_length):
            maximums.append(max_length)
            assert 0 < max_length <= avatar_service.MAX_AVATAR_METADATA_BYTES + 1
            return self.decoder.decompress(data, max_length)
        def __getattr__(self, name):
            return getattr(self.decoder, name)
    monkeypatch.setattr(avatar_service.zlib, "decompressobj", Decoder)
    content = png_with_metadata([compressed_metadata(b"zTXt", b"A" * (1024 * 1024))])
    assert_error(upload(tracking_user[1], data_url(content)), "AVATAR_TOO_LARGE")
    assert len(maximums) == 1


def test_pillow_global_limits_remain_unchanged(tracking_user):
    before = Image.MAX_IMAGE_PIXELS, PngImagePlugin.MAX_TEXT_CHUNK, PngImagePlugin.MAX_TEXT_MEMORY
    assert upload(tracking_user[1], data_url(image_bytes())).status_code == 200
    assert before == (Image.MAX_IMAGE_PIXELS, PngImagePlugin.MAX_TEXT_CHUNK, PngImagePlugin.MAX_TEXT_MEMORY)


def raw_upload(token, chunks, headers=()):
    """Drive ASGI directly so HTTP client framing cannot rewrite test headers."""
    async def call():
        reads, messages = [], []
        raw_headers = [(b"content-type", b"application/json")]
        if token:
            raw_headers.append((b"authorization", ("Bearer " + token).encode()))
        raw_headers.extend((key.encode(), value.encode()) for key, value in headers)
        async def receive():
            index = len(reads)
            assert index < len(chunks), "Endpoint read beyond the supplied body"
            reads.append(index)
            return {"type": "http.request", "body": chunks[index], "more_body": index + 1 < len(chunks)}
        async def send(message):
            messages.append(message)
        await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                   "method": "PUT", "scheme": "http", "path": PATH, "raw_path": PATH.encode(),
                   "query_string": b"", "headers": raw_headers,
                   "client": ("127.0.0.1", 2345), "server": ("testserver", 80)}, receive, send)
        start = next(m for m in messages if m["type"] == "http.response.start")
        body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
        return Response(start["status"], headers=start["headers"], content=body), len(reads)
    return run_async(call())


@pytest.mark.parametrize("token", [None, "invalid-token"])
def test_authentication_precedes_body_and_length_processing(token):
    response, reads = raw_upload(token, [], [("content-length", "999999999")])
    assert response.status_code == 401 and response.json()["error"]["code"] == "INVALID_TOKEN"
    assert reads == 0


def test_excessive_content_length_rejected_without_receiving(tracking_user):
    response, reads = raw_upload(tracking_user[1], [], [("content-length", "9" * 5000)])
    assert_error(response, "AVATAR_TOO_LARGE")
    assert reads == 0


@pytest.mark.parametrize("headers", [[], [("transfer-encoding", "chunked")], [("content-length", "1")]])
def test_oversized_streams_stop_at_received_byte_limit(tracking_user, headers):
    chunks = [b" " * avatar_request.MAX_AVATAR_REQUEST_BYTES, b"x", b"must not be read"]
    response, reads = raw_upload(tracking_user[1], chunks, headers)
    assert_error(response, "AVATAR_TOO_LARGE")
    assert reads == 2


@pytest.mark.parametrize("headers", [[], [("transfer-encoding", "chunked")]])
def test_valid_stream_without_content_length(tracking_user, headers):
    body = json.dumps({"image": data_url(image_bytes())}).encode()
    response, reads = raw_upload(tracking_user[1], [body[:20], body[20:]], headers)
    assert response.status_code == 200 and reads == 2


@pytest.mark.parametrize("value", ["0", "1", "100000", "-1", "invalid"])
def test_misleading_or_invalid_content_length_rejected(tracking_user, value):
    body = json.dumps({"image": data_url(image_bytes())}).encode()
    response, _ = raw_upload(tracking_user[1], [body], [("content-length", value)])
    assert_error(response)


def test_duplicate_content_length_rejected(tracking_user):
    response, reads = raw_upload(tracking_user[1], [], [("content-length", "1"), ("content-length", "1")])
    assert_error(response)
    assert reads == 0


def test_raw_request_boundary_and_original_image_byte_limit(tracking_user):
    body = json.dumps({"image": data_url(image_bytes())}).encode()
    exact = body + b" " * (avatar_request.MAX_AVATAR_REQUEST_BYTES - len(body))
    response, _ = raw_upload(tracking_user[1], [exact], [("content-length", str(len(exact)))])
    assert response.status_code == 200
    response, _ = raw_upload(tracking_user[1], [exact, b" "])
    assert_error(response, "AVATAR_TOO_LARGE")


def test_auth_and_rate_limit_precede_malformed_json(tracking_user):
    for _ in range(10):
        response, reads = raw_upload(tracking_user[1], [b'{"image":"private-malformed'])
        assert_error(response)
        assert reads == 1 and "private-malformed" not in response.text
    response, reads = raw_upload(tracking_user[1], [])
    assert response.status_code == 429 and reads == 0
    assert response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert int(response.headers["Retry-After"]) >= 1
    assert request("DELETE", "/users/me/avatar", tracking_user[1]).status_code == 429


def test_oversized_body_rejections_consume_shared_quota(tracking_user):
    for _ in range(10):
        response, reads = raw_upload(tracking_user[1], [], [("content-length", "524289")])
        assert_error(response, "AVATAR_TOO_LARGE")
        assert reads == 0
    assert request("DELETE", "/users/me/avatar", tracking_user[1]).status_code == 429


def test_request_body_is_never_implicitly_buffered(tracking_user, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Avatar must use bounded streaming, never Request.body/json")
    monkeypatch.setattr(avatar_request.Request, "body", forbidden)
    monkeypatch.setattr(avatar_request.Request, "json", forbidden)
    assert upload(tracking_user[1], data_url(image_bytes())).status_code == 200


def test_body_read_does_not_reserve_authentication_database_connection(tracking_user, monkeypatch):
    before = engine.pool.checkedout()
    original = avatar_request.Request.stream
    observed = []
    async def stream(request):
        observed.append(engine.pool.checkedout())
        async for chunk in original(request):
            yield chunk
    monkeypatch.setattr(avatar_request.Request, "stream", stream)
    response = upload(tracking_user[1], data_url(image_bytes()))
    assert response.status_code == 200
    assert observed == [before]
    assert request("GET", "/auth/me", tracking_user[1]).json()["avatar"] == response.json()["avatar"]


def test_slow_request_has_bounded_read_duration(tracking_user, monkeypatch):
    original = avatar_request.Request.stream
    async def slow(request):
        await asyncio.sleep(0.05)
        async for chunk in original(request):
            yield chunk
    monkeypatch.setattr(avatar_request, "AVATAR_BODY_TIMEOUT_SECONDS", 0.005)
    monkeypatch.setattr(avatar_request.Request, "stream", slow)
    assert_error(upload(tracking_user[1], data_url(image_bytes())))


def test_openapi_retains_json_upload_and_bearer_auth():
    operation = app.openapi()["paths"][PATH]["put"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert operation["requestBody"]["required"] is True
    assert schema["required"] == ["image"] and schema["properties"]["image"]["type"] == "string"
    assert schema["additionalProperties"] is False
    assert operation["security"] == [{"HTTPBearer": []}]
    assert "422" in operation["responses"]
