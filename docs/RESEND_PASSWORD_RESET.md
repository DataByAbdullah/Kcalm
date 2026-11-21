# Password-reset email delivery

Kcalm supports Resend HTTPS and explicit SMTP selection using existing dependencies.
PostgreSQL stores a durable outbox; bounded consumers run within FastAPI's lifespan.
No Redis, Celery, separate worker service, external storage, or new package is needed.
There is no provider fallback or fake delivery success.

## Architecture and guarantees

1. The existing shared IP limiter checks requests: five requests per 300 seconds
   by default, including unsuccessful requests.
2. A short transaction atomically applies a recipient cooldown and inserts a job.
   Addresses are trimmed and lowercased. Quota keys contain only HMAC-SHA256 digests
   using the existing JWT secret. Unknown/inactive recipients receive dummy jobs,
   preserving the public response and durable insert path.
3. The public response returns after persistence, without generating a reset JWT,
   waiting for a provider, or holding a transaction during email delivery. Provider
   latency is removed from response timing; this is not a constant-time guarantee.
   Database contention and account lookup can still vary.
4. Each API process claims one job at a time. PostgreSQL coordinates the global
   delivery budget, concurrency limit, and leases across instances. The claim
   transaction ends before delivery. Only primitive recipient/token snapshots
   reach the transport; no live session or ORM object does.
5. HTTPS/SMTP runs in a short-lived subprocess. The parent enforces the total
   deadline, terminates, and reaps the child on timeout/cancellation. An independent
   kernel SIGALRM terminates the child at the same absolute deadline if the parent
   dies or DNS/TLS/SMTP blocks. POSIX process/signal support is required (Railway
   Linux and local macOS); unsupported platforms fail closed.
6. Completion matches its lease nonce. Expired leases recover after the transport
   deadline plus ten seconds. Jobs and JWTs expire from the original request time;
   queue delays and retries never extend token expiry.

The outbox stores a user UUID, password fingerprint, times, attempts, lease, and
safe status/category. It stores no recipient address, JWT, raw password hash,
reset link, or credential. Deleting the user cascades jobs. Inactive, deleted,
password-changed, and expired subjects are discarded before delivery. Changes
following a claim can still produce obsolete email; reset validation rejects its
invalid token.

The dispatcher has a dedicated one-connection pool and one DB executor per API
process. Admission/claims use a PostgreSQL advisory transaction gate; lock waits
are bounded to 500 ms and statements to two seconds. Completion locks only its
own job. No lock spans delivery. Default global concurrency is two, also limited
to one child per API process. Budget one additional DB connection per process.

Default admission capacity is 500 pending/processing jobs. Terminal history is
pruned in batches of 100, retaining roughly 1,000 recent records and no more than
24 hours while consumers run. Existing rate-limit bucket retention is unchanged.

## Retries and limitations

Timeouts, provider 429 responses, network errors, and provider 5xx responses retry
with exponential backoff (30 then 60 seconds by default), up to three attempts
and within original expiry. Each attempted delivery consumes the global budget.
Budget exhaustion defers existing work. Configuration/authentication failures and
other HTTP 4xx responses are terminal and emit safe diagnostics; correct the
configuration and request another reset after the cooldown.

Resend uses the job UUID as a stable `Idempotency-Key`; retries have the same token
and payload while configuration remains unchanged. Resend documents a 24-hour key
lifetime; reset jobs expire after 30 minutes by default. Changing sender/frontend
settings during retries can change the payload for the same key, causing rejection.
Let in-flight work finish before changing settings. SMTP uses a stable Message-ID,
but has no guaranteed deduplication: ambiguous acceptance followed by a crash or
timeout may result in another copy of the same email. This is bounded, at-least-once
processing, not exactly-once or guaranteed inbox delivery.

Committed jobs survive restarts. At least one continuously running API instance
with lifespan enabled must consume jobs before expiry. Sleeping/scaled-to-zero
services cannot deliver until resumed. Disabled consumers leave work undelivered.
Database failure/full capacity prevents admission and logs a warning while the
public response remains generic. There is no unreliable in-memory fallback and
no delivery promise from HTTP 200. Distributed floods of distinct recipients can
still exhaust queue/DB capacity; retain deployment-level abuse protection.

## Railway variables and migration

Set variables privately on the backend service; never put keys in Git, screenshots,
frontend variables, or NEXT_PUBLIC_ variables. This implementation changes no
Railway variables or deployed databases.

| Variable | Value/default |
| --- | --- |
| EMAIL_PROVIDER | `resend` or `smtp`; default `smtp` for compatibility |
| RESEND_API_KEY | Private sending key, preferably restricted to the sending domain |
| RESEND_FROM_EMAIL | Authorized sender, optionally with display name |
| FRONTEND_PASSWORD_RESET_URL | Complete HTTPS frontend reset URL for staging/production |
| EMAIL_TIMEOUT_SECONDS | Per-operation HTTPS/SMTP socket timeout; 10 seconds, range >0–60 |
| EMAIL_CONNECT_TIMEOUT_SECONDS | HTTPS connect timeout; 5 seconds, range >0–30 |
| EMAIL_DELIVERY_DEADLINE_SECONDS | Total transport deadline including startup/DNS; 20 seconds, range >0–120 |
| PASSWORD_RESET_DISPATCHER_ENABLED | `true`; at least one running consumer required |
| PASSWORD_RESET_POLL_SECONDS | Idle interval; 1 second, range 0.1–60 |
| PASSWORD_RESET_MAX_CONCURRENT_DELIVERIES | Global cap; 2, range 1–8 |
| PASSWORD_RESET_MAX_PENDING_JOBS | Admission capacity; 500, range 1–10000 |
| PASSWORD_RESET_MAX_ATTEMPTS | Includes first attempt; 3, range 1–5 |
| PASSWORD_RESET_RETRY_SECONDS | Initial exponential delay; 30, range 1–300 |
| RATE_LIMIT_PASSWORD_RESET_RECIPIENT_WINDOW_SECONDS | Recipient cooldown; 60 seconds, minimum 1 |
| RATE_LIMIT_PASSWORD_RESET_RECIPIENT_REQUESTS | Fixed at 1 to enforce cooldown |
| RATE_LIMIT_PASSWORD_RESET_PROVIDER_REQUESTS | Global delivery attempts per window; 30, minimum 1 |
| RATE_LIMIT_PASSWORD_RESET_PROVIDER_WINDOW_SECONDS | Global budget window; 60 seconds, minimum 1 |

Existing DATABASE_URL, JWT_SECRET, APP_ENV and auth settings still apply.
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES remains 30 by default. All instances must use
the same database, JWT secret, quotas, and concurrency settings for shared limits.
Set budgets for the provider account's actual limits; this does not coordinate
other applications using that account/key.

Additive migration **20261120_0025**, following **20261118_0024**, creates only
`password_reset_jobs`, indexes, and constraints. It preserves existing users and
historical application data. An operator must run `alembic upgrade head` before
starting this code against that environment. The application DB role needs normal
SELECT/INSERT/UPDATE/DELETE access to this table and the existing rate-limit table.
No PostgreSQL extensions are required.

Before rollback, stop consumers and decide how pending work will be handled.
`alembic downgrade 20261118_0024` drops only the outbox and necessarily discards
queued work, preserving users. Rolling back to synchronous code restores its
former timing/race risks. Do not mix old synchronous senders and new consumers
in a rolling deployment; prefer a coordinated rollout after migration. Validate
the exact deployment image contains Python, `app.scripts.password_reset_delivery`,
CA certificates, and permits subprocesses/SIGALRM. No dependencies were added.

## Staging, production, and safe testing

Use an isolated staging database, staging key, and staging frontend URL. Configure
EMAIL_PROVIDER=resend, a private key, and either a verified staging sender or
`onboarding@resend.dev`. The resend.dev sender can send only to the Resend account's
authorized recipient. Register that authorized address in the test environment.
Other recipients require a verified sender domain. Kcalm's generic response does
not bypass this restriction or reveal rejection to the caller.

An operator should verify migration, consumer startup, authorized submission,
restart recovery, two-instance quotas, retry behavior, and graceful shutdown in
staging. Inspect safe events and the authorized Resend dashboard. Never put keys,
recipient addresses, tokens, or complete reset links in logs, tickets, or screenshots.
Live verification requires a separate explicit operator action. Automated tests
mock providers and must never send real email or use deployed databases.

Production requires a verified domain you control and the DNS records Resend
specifies, including SPF/DKIM. Wait for verified status; use a dedicated production
key, verified sender, and production HTTPS frontend URL. Do not use the test sender
for arbitrary users or reuse staging keys/URLs.

Resend uses fixed `https://api.resend.com/emails`, verified TLS, no redirects, and
no proxy/environment inheritance. SMTP settings do not participate. Production
startup warns safely about invalid/missing provider or frontend configuration;
this is not a key/domain/connectivity/consumer-health check.

## API and frontend contract

`POST /api/v1/auth/forgot-password` remains unauthenticated:

```json
{"email":"user@example.com"}
```

Known, unknown, inactive, cooldown/capacity-suppressed, and internally failed
requests retain HTTP 200 and the existing body:

```json
{"message":"If an account exists for this email, a password reset link has been sent."}
```

This wording is retained for compatibility/enumeration protection, not delivery
confirmation. Existing validation, IP-limit HTTP 429 `RATE_LIMIT_EXCEEDED` and
`Retry-After` remain unchanged. Failure in the existing IP limiter retains HTTP
503 `RATE_LIMIT_UNAVAILABLE`. Recipient suppression does not produce a specific
429. Frontends should show generic confirmation, honor Retry-After for IP limits,
and allow for delivery delay/cooldown. No request/response schema changes are needed.

Links use FRONTEND_PASSWORD_RESET_URL and a URL-encoded `token` parameter, replacing
old token parameters and preserving others. Credential-bearing URLs, fragments,
invalid ports and unsafe schemes are rejected. Production rejects localhost;
HTTP localhost remains supported for local development. The frontend reads token
and submits the unchanged `POST /api/v1/auth/reset-password` body:

```json
{"token":"<token>","new_password":"<new-password>"}
```

Hashing, expiry, validation, and error codes remain unchanged. The password update
now atomically matches the expected old hash and active user and increments
`token_version = token_version + 1`. Exactly one concurrent token use wins;
losing/repeated attempts receive HTTP 400 `INVALID_PASSWORD_RESET_TOKEN` and cannot
overwrite the successful password. Concurrent session-revocation increments are
not lost by this update.

Keep reset URLs out of analytics, access logs, error reports, and third-party
requests. Use a restrictive referrer policy on the frontend reset page.

## Monitoring and troubleshooting

Password-reset loggers explicitly enable INFO and use a JSON field allowlist:
level, event, provider, category, exception_class, numeric status_code, and reason.
The formatter omits arbitrary message arguments, exception messages/tracebacks,
provider bodies, tokens, addresses, links, and keys. Child stderr is discarded and
bounded child results accept only validated categories/class names. Do not enable
request/header/body, SMTP-debug, SQL-parameter, or APM-local-variable capture for
this flow. External logging configuration must preserve safe handling.

| Category | Meaning/action |
| --- | --- |
| queued | Work committed; not provider submission/inbox confirmation |
| suppressed | Recipient cooldown; public response stays generic |
| accepted | Provider/SMTP accepted submission; verify delivery/bounce/spam separately |
| provider_not_configured | Correct provider credentials/sender/frontend URL |
| authentication_failed | Check/rotate credentials privately; permanent for this job |
| rate_limited | Provider 429; bounded retry subject to shared budget |
| timeout | Overall or transport deadline; retry; delivery may be ambiguous |
| provider_error | HTTP/network/SMTP/child/invalid acceptance; retry depends on status |
| queue_unavailable | DB failure or admission capacity; alert on persistence_failed/queue_capacity |
| dispatcher_disabled | Another running consumer is required |
| stale_result | Changed lease; completion fenced and ignored |

Configuration reasons include missing_provider_credentials,
invalid_provider_credentials, incomplete_smtp_credentials, invalid_sender, and
frontend_url_not_configured. No values are logged. HTTP 403 is provider_error:
inspect sender/domain restrictions or permissions in the authorized dashboard.
Error/redirect bodies are not read. Success bodies are limited to 8 KiB; compressed
responses are rejected. Child input is limited to 64 KiB and output to 4 KiB;
recipient/token/key are never in argv or inherited environment. The transport
child receives no database URL or JWT signing key.

Monitor consumer health, queue age/capacity, failed jobs, attempt counts, and DB
contention using authorized aggregate queries, for example:

```sql
SELECT status, count(*) FROM password_reset_jobs GROUP BY status;
SELECT min(created_at), count(*) FROM password_reset_jobs WHERE status = 'pending';
SELECT failure_category, count(*) FROM password_reset_jobs
WHERE status = 'failed' GROUP BY failure_category;
```

Do not interpret HTTP 200, queued, or accepted as inbox delivery. After parent
failure, status may remain processing until lease recovery. Terminal records are
short-lived diagnostics, not a permanent audit archive.

## SMTP compatibility

EMAIL_PROVIDER=smtp retains SMTP_HOST, SMTP_PORT (587), SMTP_FROM_EMAIL,
SMTP_USERNAME, SMTP_PASSWORD, and SMTP_USE_TLS (true). Both credentials can be
empty for an anonymous relay; supplying only one is a configuration error.
STARTTLS uses verified TLS. EMAIL_TIMEOUT_SECONDS controls socket timeout; the
subprocess enforces the total deadline even during DNS/SMTP. Use TLS and an
authorized sender when deployed. Unconfigured providers never log acceptance.

## Automated verification

Use an isolated migrated PostgreSQL database, synthetic credentials, and
`PASSWORD_RESET_DISPATCHER_ENABLED=false` so tests explicitly drive/mock dispatch:

```bash
python -m pytest tests/test_password_reset_security.py tests/test_password_reset_migration.py tests/test_password_reset_email.py tests/test_auth.py tests/test_auth_hardening.py tests/test_rate_limits.py tests/test_migration_integrity.py
python -m pytest
python -m pip check
git diff --check
```

Tests use real independent PostgreSQL transactions for reset races, atomic HMAC
cooldowns, shared delivery budgets/concurrency, recovery/fencing and lock timeouts.
They exercise lifecycle disposal, connection release, real child termination and
reaping, child secret isolation, logs, provider mocks, original expiry, and public
contracts. The lifecycle test explicitly enables its consumer with fake delivery.

Official references:

- [Resend API](https://resend.com/docs/api-reference/emails/send-email)
- [Idempotency](https://resend.com/docs/dashboard/emails/idempotency-keys)
- [Provider errors](https://resend.com/docs/api-reference/errors)
- [resend.dev restrictions](https://resend.com/docs/knowledge-base/403-error-resend-dev-domain)
- [Domain verification](https://resend.com/docs/dashboard/domains/introduction)
- [Python interval timers](https://docs.python.org/3/library/signal.html#signal.setitimer)
