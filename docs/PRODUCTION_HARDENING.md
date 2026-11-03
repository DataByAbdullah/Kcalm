# Production Hardening

Apply `alembic upgrade head` before starting API workers. The additive migration is
`alembic/versions/20261103_0021_admin_and_rate_limits.py`, revision `20261103_0021`,
down revision `20261028_0020`. It adds non-null `users.is_admin` with database default
false and `rate_limit_buckets`. Existing users remain non-admin until explicitly promoted
through trusted database operations. There is no public role-assignment endpoint.

Applied Alembic migrations are immutable. Never rename an existing migration file or change an existing revision/down_revision after it may have been deployed. Schema changes must always be introduced through a new migration.

## Authorization and Sessions

`UserResponse` exposes `is_admin` in registration, `/auth/me` and profile-name update
responses. Registration ignores attempted admin assignment and always creates a normal
user. `require_admin` requires valid authentication and returns `403 ADMIN_REQUIRED`
for non-admins. It protects only recipe POST/PATCH/DELETE and USDA import. Recipe
reads, candidate preview, execution sessions and USDA search remain available to normal
authenticated users.

Authenticated `POST /api/v1/auth/logout` atomically increments the user's token version
and commits, returning `200 {"message":"Logged out successfully."}`. This invalidates
all earlier access and refresh tokens for that user across devices. Old access tokens
return `401 INVALID_TOKEN`; old refresh tokens return `401 INVALID_REFRESH_TOKEN`.
Password login still works. Database failures roll back and return `500 LOGOUT_FAILED`.

Forgot-password returns `200` with
`{"message":"If an account exists for this email, a password reset link has been sent."}`
for known emails, unknown emails and expected SMTP/network/timeout delivery failures,
subject to the same per-client rate limit. Operations receive a generic warning on
delivery failure without addresses, tokens, credentials or SMTP exception details.
SMTP connections have a 10-second timeout. Unrelated programming errors propagate.

## Production Configuration

`APP_ENV=production` or `prod` (case-insensitive) requires a JWT secret different from
the development default. `create_app()` fails immediately otherwise, without printing
the configured secret. Production disables `/docs`, `/redoc` and `/openapi.json`.
Development/test keep the default secret and existing documentation routes available.

## Shared Rate Limits

Limits apply in every environment and across workers. Each quota uses a fixed window
starting with the first request; an expired bucket resets atomically on its next request.
Counts include unsuccessful attempts. Invalid authentication and admin authorization
are checked before consuming an authenticated user's quota.

| Scope | Defaults | Identity | Environment variables |
| --- | --- | --- | --- |
| `POST /auth/register` | 5 / 60 seconds | Client IP | `RATE_LIMIT_REGISTER_REQUESTS`, `RATE_LIMIT_REGISTER_WINDOW_SECONDS` |
| `POST /auth/login` | 10 / 60 seconds | Client IP | `RATE_LIMIT_LOGIN_REQUESTS`, `RATE_LIMIT_LOGIN_WINDOW_SECONDS` |
| `POST /auth/forgot-password` | 5 / 300 seconds | Client IP | `RATE_LIMIT_FORGOT_PASSWORD_REQUESTS`, `RATE_LIMIT_FORGOT_PASSWORD_WINDOW_SECONDS` |
| All `/api/v1/ai/*` routes | Shared 30 / 60 seconds | Authenticated user ID | `RATE_LIMIT_AI_REQUESTS`, `RATE_LIMIT_AI_WINDOW_SECONDS` |
| `POST /foods/usda/import/{fdc_id}` | 20 / 60 seconds | Authenticated admin ID | `RATE_LIMIT_USDA_IMPORT_REQUESTS`, `RATE_LIMIT_USDA_IMPORT_WINDOW_SECONDS` |

All values must be positive integers. Routes are relative to `/api/v1` unless shown in
full. A blocked request returns the existing envelope with `429 RATE_LIMIT_EXCEEDED`
and integer `Retry-After` seconds remaining in its window (at least 1). Blocked requests
do not extend the window. A limiter database failure returns `503 RATE_LIMIT_UNAVAILABLE`.

PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` with a conditional update enforces quotas
atomically. A separate transaction preserves quota even if the endpoint later rolls back.
The primary key is an HMAC-SHA256 digest of scope and identity using the JWT secret;
raw IPs, emails and user IDs are absent from bucket records. There is one reusable
row per identity/scope, rather than a row per request. Rotating the secret resets the
bucket namespace. Expired rows can be periodically deleted using the indexed `expires_at`;
the application reuses/reset rows correctly without a cleanup job.

Client identity uses the ASGI connection's client host. The limiter does not read
`X-Forwarded-For`. Configure the ASGI server's trusted proxy addresses correctly when
deploying behind a proxy, so trusted forwarding produces the actual client address.

## Daily Metrics Partial PUT

For a new owned date, supply all three non-null metrics. Missing fields return controlled
`422 DAILY_METRICS_INCOMPLETE_CREATE`; no zero/default values are invented. For an
existing owned record, supply at least one metric. Only supplied columns are updated,
including during concurrent partial requests. `{}`, explicit nulls and extra fields
return 422; strict types/ranges and UTC date limits remain unchanged. PATCH is unsupported.
Example: after `{ "water_glasses":8, "fruit_veg_servings":5, "sleep_hours":7.5 }`,
PUT `{ "water_glasses":10 }` retains servings 5 and sleep 7.5.

Tests run against a dedicated migrated PostgreSQL database; test fixtures reset limiter
buckets between tests without disabling the limiter or increasing the default quotas.

## Verification

Verified on 2026-11-03 against isolated PostgreSQL databases:

- `alembic heads`: exactly `20261103_0021 (head)`.
- Upgrade from `20261028_0020` to head succeeded; an existing user retained its data
  and received `is_admin=false`.
- Focused auth/logout, admin, recipes, candidates, USDA, production config/docs, SMTP,
  rate-limit, daily-metrics and migration tests: `147 passed in 37.26s`.
- Full `pytest -q`: `528 passed in 641.41s (0:10:41)`.
