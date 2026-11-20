# User avatars

Avatars are stored in the nullable `users.avatar_data_url` Text column. Existing
users default to SQL NULL. Public responses expose `avatar`, never the internal
column name. There is no external storage, AI service, or image generation.

## Upload or replace

`PUT /api/v1/users/me/avatar` requires the existing Bearer access token and JSON:

```http
PUT /api/v1/users/me/avatar
Authorization: Bearer <access-token>
Content-Type: application/json

{"image":"data:image/jpeg;base64,<complete-base64-image>"}
```

Replace the placeholder with the complete Base64 image bytes. Only `image` is
accepted; extra fields, including user IDs, are rejected. The authenticated user
is the sole mutation target. A nutrition profile is not required.

Success is HTTP 200 with `Cache-Control: no-store` and the existing user response:

```json
{
  "id": "7e87c490-9caf-4c39-ac7b-4a9279cfef2b",
  "email": "user@example.com",
  "full_name": "Example User",
  "membership_tier": "free",
  "is_active": true,
  "is_admin": false,
  "avatar": "data:image/jpeg;base64,<complete-base64-image>"
}
```

Upload replaces the previous value on the same user row. Failed validation leaves
the previous avatar unchanged. Concurrent successful mutations use PostgreSQL row
update serialization; the last committed mutation wins. Validation occurs before
the update, outside its write lock.

## Delete and read

`DELETE /api/v1/users/me/avatar` requires authentication and no body. It sets SQL
NULL and returns HTTP 204 with an empty body. Deletion is idempotent, subject to
the shared rate limit.

- `GET /api/v1/auth/me` includes `"avatar": null` or the complete Data URL.
- `GET /api/v1/users/profile` includes the same field and all existing profile
  fields. Its existing profile-not-found behavior is unchanged.
- Registration, current-user PATCH, and profile POST/PATCH responses also include
  the additive avatar field through their public response schemas.
- `GET /api/v1/users/me/export` includes `user.avatar`; its existing version and
  other fields remain unchanged, with `Cache-Control: no-store`.
- `DELETE /api/v1/users/me` already hard-deletes the user row in a transaction.
  This removes its avatar too. There is no soft-deleted or anonymized avatar copy
  or external object to clean up. Existing token and cascade behavior is retained.

The ORM column is deferred so authentication and unrelated queries avoid loading
the potentially 400 KB value. Public user/profile serialization and export load
it when needed. Public profile responses extend the internal profile at the route
boundary; avatar contents never become planning inputs or stale-input checks.
JWT access, refresh, and password-reset claims are unchanged and avatar-free.

## Validation

Only static JPEG (`image/jpeg`), PNG (`image/png`), and WebP (`image/webp`) are
accepted. GIF, SVG, animated PNG/WebP, external URLs, MIME parameters, and non-image
payloads are rejected.

- Decoded image: at most **307200 bytes (300 KiB)**, inclusive.
- Base64: at most **409600 characters**. Oversized encoded strings are rejected
  before Base64 decoding or image processing. Complete Data URLs are at most
  409623 characters (409622 for PNG).
- Width and height: each at most **4096 pixels**.
- Pixel count: at most **4194304 pixels**, inclusive.
- PNG ancillary metadata: at most **524288 bytes (512 KiB)** cumulatively,
  including expanded text/ICC data and metadata headers. Every chunk counts,
  including duplicate keys and chunks after pixel data. The server validates
  chunk boundaries and CRCs before Pillow opens the image. Compressed `zTXt`,
  `iTXt`, and `iCCP` streams use bounded zlib output and must be complete, with
  valid checksums and no trailing or concatenated streams. The server never uses
  an unbounded decompressor flush or changes process-wide Pillow settings.
- Canonical standard Base64 is required, including correct padding and pad bits;
  whitespace and malformed/URL-safe encodings are rejected.
- MIME, file signature, and actual decoder format must agree. Only the declared
  allowed decoder is invoked; structural verification and full pixel decoding
  must both succeed.
- Dimensions are checked before full pixel decoding. Decompression-bomb warnings
  and errors are rejected. Global Pillow limits are not changed or disabled.
- WebP lossy/lossless/extended canvas headers are checked before opening its
  native decoder, which can allocate a canvas during initialization.

JPEG APP/COM metadata and WebP EXIF/XMP/ICC metadata are not decompressed by the
decoders used here. Their raw size is bounded by the 307200-byte image limit.
The application does not interpret EXIF/XMP or perform color-profile conversion;
Pillow may inspect bounded EXIF fields such as JPEG DPI during image opening.

The upload endpoint authenticates and consumes the shared mutation quota before
reading or parsing its body. It releases its read-only authentication transaction
before waiting for body bytes, so slow uploads do not reserve a database
connection. Quota is already committed independently; the same authenticated user
remains the mutation target.

The request stream is read into a bounded buffer, never through `Request.body()`
or `Request.json()`:

- Raw JSON body: at most **524288 bytes (512 KiB)**. This includes the maximal
  409623-byte standard Data URL and more than 100 KiB for JSON overhead.
- Excessive `Content-Length` is rejected before body reading. Actual received
  bytes are checked independently, including chunked requests and requests
  without `Content-Length`. Duplicate, invalid, or mismatched lengths are rejected.
- A body read must finish within **30 seconds**; disconnects and read timeouts
  return the existing `INVALID_AVATAR` error when a response can still be sent.

Standard JSON uploads keep the same request and response contract. Excessively
escaped strings or whitespace cannot bypass the raw byte limit. Bearer access
tokens remain required; malformed unauthenticated requests return the existing
authentication error before any body is processed.

Normalization produces a lowercase header and canonical Base64, preserving the
validated compressed bytes. It does not resize, recompress, or strip metadata.
Clients can crop, resize, and strip metadata before upload; server validation is
authoritative.

## Errors and limits

Errors retain Kcalm's existing structure without image or decoder details:

```json
{"error":{"code":"INVALID_AVATAR","message":"Provide a valid static JPEG, PNG, or WebP image Data URL.","details":{}}}
```

| HTTP | Code | Meaning |
| --- | --- | --- |
| 422 | `INVALID_AVATAR` | Invalid JSON/shape, body framing/read, Data URL, Base64, MIME/content, corruption, metadata, or animation |
| 422 | `AVATAR_TOO_LARGE` | Raw/encoded/decoded size, metadata expansion, dimension, pixel, or decompression limit |
| 401 | Existing `INVALID_TOKEN` / `TOKEN_EXPIRED` | Existing authentication behavior |
| 403 | Existing `USER_INACTIVE` | Existing inactive-account behavior |
| 429 | Existing `RATE_LIMIT_EXCEEDED` | Honor the returned `Retry-After` header |
| 503 | Existing `RATE_LIMIT_UNAVAILABLE` | Limiter failed closed |
| 500 | `AVATAR_UPDATE_FAILED` | Database mutation failed and was rolled back |

PUT and DELETE share **10 requests per 60-second fixed window per authenticated
user**, using the existing atomic PostgreSQL limiter across workers. All
authenticated attempts consume quota, including malformed JSON, excessive body
lengths, and schema/image validation failures. Authentication and quota enforcement
precede body processing; exhausted users receive 429 without reading their body.
Other users and other
scopes have separate buckets. Defaults follow existing settings conventions:
`RATE_LIMIT_AVATAR_REQUESTS=10`, `RATE_LIMIT_AVATAR_WINDOW_SECONDS=60`. Keep these
defaults for the stated policy. Limiter rows contain HMAC identity digests, never
avatars or raw user IDs.

The feature does not log image contents or expose internal exceptions. Avoid
request/response-body or SQL parameter/result logging for personal image data.

## Migration and dependency

The only dependency added is `Pillow==13.0.0`. Standard wheels include JPEG, PNG,
and WebP; custom source builds must provide these codecs. Tests exercise all three.

Revision **`20261118_0024`**, parent **`20261110_0023`**. After selecting the intended
database through the existing configuration, install dependencies and migrate
before starting the updated API:

```sh
python -m pip install -r requirements.txt
python -m alembic upgrade head
```

Upgrade adds only a nullable Text column without modifying existing user data or
backfilling images. For feature rollback, stop the updated API, restore the prior
application version, and downgrade:

```sh
python -m alembic downgrade 20261110_0023
```

Downgrade drops the avatar column and its values while preserving all other user
data. Export avatars first if they must survive rollback. Implementation tests
and migrations run only against isolated local PostgreSQL, never staging or
production.

## Frontend integration

Read the selected JPEG/PNG/WebP as a Data URL. Crop/resize to the documented limits
and send `{"image": dataUrl}` with the existing Authorization header. Use returned
`avatar` directly as an image source, falling back when null. An application CSP
must permit `data:` under `img-src`. Do not inject it into HTML.

Replace cached user/profile avatar state after PUT succeeds; clear it after DELETE
204. Preserve the old avatar on 422 and show the validation error. Honor 429's
`Retry-After` without automatic upload loops. Preserve existing 401/403 handling.
Users without nutrition profiles can use auth/me even when users/profile is 404.

No frontend files, meal-plan, consumption, nutrition, swap, grocery, or
authentication behavior are changed.

## Testing

Against a migrated isolated PostgreSQL database with UTC sessions:

```sh
python -m pytest tests/test_user_avatar.py tests/test_user_avatar_migration.py
python -m pytest tests/test_user_avatar_security.py
python -m pytest
```

Coverage includes formats, corruption, MIME/Base64 rejection, size boundaries,
decompression and preallocation limits, shared/concurrent quotas, isolation,
export/deletion, JWT privacy, rollback, deferred reads, planning independence, and
upgrade/downgrade preserving existing users. Security regressions additionally
cover compressed and cumulative metadata expansion before Pillow, malformed
metadata, bounded decompressor output, raw and chunked body limits, missing or
misleading lengths, authentication order, malformed-JSON quotas, body deadlines,
and OpenAPI compatibility.

References: [Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html),
[WebP container specification](https://developers.google.com/speed/webp/docs/riff_container).
