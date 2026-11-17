# Consumption protection and plan updates

Daily nutrition still sums every active consumption record, including logs on
archived plans and repeated consumption of the same food. No production records
are deleted, deduplicated, reclassified, or excluded. No migration is required.

## Protected days and weeks

Any active meal log protects its user and log date, even when its plan is already
archived. A generated protected day cannot be explicitly archived or recreated.
`DELETE /meal-plans/{id}` returns HTTP 409 `MEAL_PLAN_CONSUMPTION_EXISTS` before
changing status. Its details include `conflict_dates`, `meal_plan_id`, and
`retryable: false`. Same-item logging/corrections remain upserts; resetting a log
remains an explicit supported operation on generated plans. After all relevant
logs have been explicitly reset, ordinary unconsumed-plan replacement is allowed.

An active week containing consumption is retained as a complete weekly container.
Profile updates preserve that week and all its current daily members. Explicit
whole-week archive is rejected atomically; individual members cannot be archived
while their week contains consumption, including members with no logs yet. The
409 details include the relevant `weekly_plan_id` (and `meal_plan_id` for a daily
request). This prevents missing days, inaccessible remaining meals, and an
archived parent that cannot support grocery lists.

Every remaining unlogged item, including items on entirely unconsumed days of a
protected week, can still be swapped through existing endpoints. Swaps preserve
plan/item IDs and schedules and leave consumed meals and nutrient snapshots
unchanged. Existing target/count/schedule snapshots are retained; a profile change
does not rewrite an already consumed day/week. Updated candidate preferences are
used for subsequent swaps. New preferences/counts/schedules apply to new plans
outside the protected week. There is no new full-day regeneration endpoint for a
member of a protected week; supported remaining-meal updates use in-place swaps.

Profile PATCH still returns 200 and saves the requested profile. Unconsumed future
standalone plans and wholly unconsumed weeks continue to be invalidated normally.
The weekly listing/detail and existing grocery creation/regeneration routes remain
usable for retained consumed weeks. After swapping recipes, clients can use the
existing grocery regeneration endpoint to refresh an existing shopping list.

Historical already archived consumed plans remain archived and readable. This
change prevents new stranding; it does not silently reactivate or repair existing
production history. Such dates continue to reject full-day recreation. Repeated
archive of a fully archived plan/week remains idempotent. Standalone food logs do
not prevent plan creation because they have no replaceable meal-plan-item IDs.

## API responses

Paths and request/response schemas are unchanged. Existing generated-plan conflicts
retain precedence (`PLAN_ALREADY_EXISTS`, `WEEKLY_PLAN_ALREADY_EXISTS`, and
`DAILY_PLAN_ALREADY_EXISTS_FOR_WEEK`). A consumed date with no generated plan
returns 409 `MEAL_PLAN_CONSUMPTION_EXISTS` on creation. Weekly creation preflights
the whole range and rechecks before a single atomic save; no partial week is saved.

Regular and AI swaps of logged items return 409
`MEAL_PLAN_ITEM_ALREADY_LOGGED` with `details.meal_plan_item_id`. AI swaps reject
already logged items before external interpretation and recheck before saving.

Concurrent changes to profile/planned meals/adaptive consumption inputs invalidate
a prepared result: HTTP 409 `MEAL_PLAN_INPUTS_CHANGED`, `details.retryable: true`,
and `Retry-After: 1`. No prepared result is applied when that validation fails.

Contended user locks wait at most two seconds (or the deployment's shorter
configured lock timeout). Lock timeout, deadlock, or serialization failure during
acquisition rolls back the transaction and returns HTTP 503 `MEAL_PLAN_BUSY`,
`details.retryable: true`, and `Retry-After: 1`. A deleted authenticated user returns
401 rather than an unhandled missing-row exception.

## Frontend developer actions

- Treat a successful profile PATCH as saved even if a following archive request
  returns a protection conflict. Do not clear the day's ready state or logged IDs.
- On `MEAL_PLAN_CONSUMPTION_EXISTS`, stop archive/recreate attempts and fetch/reuse
  the retained day/week using the returned IDs or existing date lookup. Show that
  remaining unlogged meals can be swapped. This conflict is not automatically
  retryable. Batch archive callers must handle protected responses independently.
- Disable swaps for logged items and handle `MEAL_PLAN_ITEM_ALREADY_LOGGED` when
  another request logged the item concurrently. Refetch logging state.
- For `MEAL_PLAN_BUSY` and `MEAL_PLAN_INPUTS_CHANGED`, refetch current state and use
  bounded retries with the supplied delay. Reuse a plan created by a competing
  request when an existing-plan conflict is returned.
- Regenerate an existing grocery list after in-place meal swaps when needed.

No frontend files are changed by this backend implementation.

## Transactions and concurrency

Planning uses a separate read-only REPEATABLE READ snapshot. Daily/weekly/adaptive
solving runs without a user write lock; swap solving runs after its read snapshot
has closed. The application write sessions explicitly use READ COMMITTED so a
query after waiting on the user lock sees committed consumption and plan changes.

Only eligibility validation and persistence hold `SELECT ... FOR UPDATE` on the
user row. Every cooperating logging/reset/archive/profile/swap/create writer uses
the same lock. This covers empty dates, archived historical logs, and concurrent
creations. Nested acquisition in the same transaction is safe. Temporary timeout
settings are restored after successful acquisition; failures roll back all work.

After preparation, creation rechecks profile inputs, generated-plan conflicts,
and consumption under the lock. Weekly preparation uses one consistent snapshot,
then saves all seven days in one short write transaction. Adaptive creation also
rechecks its source consumption inputs and saves its adaptation metadata atomically.
Swaps recheck plan status, target logging, profile inputs, and the plan's nutrition
signature before updating the original item ID.

Planning API handlers release their authentication-only read transaction before
opening the snapshot, avoiding two checked-out connections per request. Internal
service callers retain ownership of their own transaction and may use an additional
connection. Read snapshots retain MVCC versions while generation runs. Per-user write contention is bounded; deployments should
still monitor pool utilization and planning latency. Catalog edits are not
serialized by the per-user mutex; ingredient and nutrient inputs are frozen in
the same planning snapshot so later edits cannot mix their versions during saving. Direct SQL or future consumption mutation paths
must cooperate with the locking protocol. The guard is not historical deduplication.

## Verification

Regression coverage includes protected archive/profile flows, complete retained
weeks and groceries, legacy archived intake, repeated food consumption, same-item
logging/reset, actual PostgreSQL lock waits/timeouts, solving without user locks,
stale-profile/swap rejection, competing daily/weekly creation, and rollback after
multiple flushed days. Run tests serially against an isolated migrated PostgreSQL
database, with UTC database sessions. The unrelated notification timestamp issue
is not changed here. The new persistence tests use real feasibility solving and
the existing supported optimization-timeout fallback for predictable runtime.
