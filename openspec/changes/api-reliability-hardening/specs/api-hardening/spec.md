## ADDED Requirements

### Requirement: Authenticated mutating endpoints

Every state-mutating HTTP endpoint SHALL require a valid credential via a shared
`require_auth` dependency applied at the router level (`dependencies=[Depends(require_auth)]`),
so no order placement, cancellation, kill-switch, paper reset, strategy start/stop, or
broker-sync trigger is reachable unauthenticated. Read-only endpoints MAY remain open. The
credential SHALL be sourced from settings (`get_settings()`), never hard-coded.

#### Scenario: Unauthenticated mutating request is rejected

- **WHEN** a client calls `POST /api/v1/risk/kill` (or any mutating route) without a valid credential
- **THEN** the API responds `401 Unauthorized` and performs no state change

#### Scenario: Authenticated mutating request proceeds

- **WHEN** a client calls the same route with a valid credential
- **THEN** the request is processed normally

### Requirement: Constrained request validation

Request bodies and query parameters SHALL be validated by typed Pydantic models and
constrained parameters rather than raw `request.json()` or unbounded inputs. Order quantity
SHALL enforce `Field(gt=0)`; list endpoints SHALL bound `limit` via a shared `PaginationParams`
dependency (`Query(ge=1, le=500)`); date query parameters SHALL be parsed by a single shared
`parse_ist_date()` helper that returns `400` on malformed input.

#### Scenario: Non-positive order quantity is rejected

- **WHEN** an order is placed with `qty <= 0`
- **THEN** the API responds `422` and no order reaches the broker or the lot-freeze check

#### Scenario: Malformed date query returns 400

- **WHEN** a client passes `date=not-a-date` to a journal endpoint
- **THEN** the API responds `400` instead of raising an unhandled `500`

#### Scenario: Oversized page limit is rejected

- **WHEN** a client requests a list endpoint with `limit=100000`
- **THEN** the API responds `422` (limit exceeds the bounded maximum)

### Requirement: Non-blocking route handlers

Async route handlers SHALL NOT perform blocking work (synchronous file I/O, `yaml`, `glob`,
sync DB drivers, or CPU-bound loops) directly on the event loop; such work SHALL be offloaded
via `run_in_threadpool`/`asyncio.to_thread`. The legacy backtest routes SHALL either declare a
real `Depends(get_db)` session and offload their sync engine, or be retired in favour of the
active warehouse routes.

#### Scenario: Legacy backtest list route no longer 422s

- **WHEN** a client calls `GET /api/v1/backtests`
- **THEN** the API responds `200` (the `session` parameter resolves as a dependency, not a required query param)

#### Scenario: Sync backtest engine does not block the loop

- **WHEN** a backtest run is triggered through the API
- **THEN** the synchronous replay executes in a worker thread and the event loop stays responsive

### Requirement: Bounded database connection pools

The PostgreSQL async engine SHALL configure `pool_recycle` and `pool_timeout` so idle
connections closed by the database/proxy are recycled rather than reused stale. The MongoDB
(Motor) client SHALL configure `socketTimeoutMS`, `connectTimeoutMS`, `maxPoolSize`, and
`maxIdleTimeMS` so a stalled operation cannot hang a coroutine indefinitely. All pool sizing
SHALL be tunable via settings.

#### Scenario: Stale PostgreSQL connection is recycled

- **WHEN** a pooled connection has been idle beyond `pool_recycle`
- **THEN** the engine discards and reopens it rather than raising on a dead socket

#### Scenario: Stalled MongoDB operation times out

- **WHEN** a MongoDB operation exceeds `socketTimeoutMS`
- **THEN** the driver raises a timeout the caller can handle, rather than hanging the coroutine forever

### Requirement: Idempotent order fills

An order fill SHALL be idempotent: `_fill` (paper and live brokers) SHALL be a no-op once the
order's status is already filled, so a duplicate broker callback, a reconnect replay, or a
race between the immediate-fill path and the pub/sub run-loop cannot double-book a trade or
double the position.

#### Scenario: Duplicate fill callback is ignored

- **WHEN** `_fill` is invoked twice for the same order (e.g. immediate MARKET fill then a tick, or a duplicate TRADED alert)
- **THEN** exactly one `Trade` is recorded and the position moves by the order quantity once

### Requirement: Correct cost basis on position reversal

`upsert_position` SHALL, when a single fill reverses a position through zero (long→short or
short→long), book realized P&L on the closed quantity AND reset `avg_price` to the reversing
fill price for the residual opposite-side quantity, so subsequent unrealized MTM reflects the
true entry of the new leg.

#### Scenario: Long flipped to short re-bases avg price

- **WHEN** a `+75 @ 100` position receives a `SELL 150 @ 120` fill
- **THEN** realized P&L is booked on 75 units and the residual `-75` position carries `avg_price = 120` (unrealized at ltp 120 is 0, not −1500)

### Requirement: Durable journal metadata edits

Editing a journal day's metadata (notes/tags/screenshots) SHALL NOT overwrite that day's stored
trades or stats. A metadata edit for any day SHALL load the day's existing trades before the
next flush so the persisted document retains them.

#### Scenario: Editing a past day's notes preserves its trades

- **WHEN** a client edits metadata for a past day that has stored fills and P&L
- **THEN** the flushed document retains the day's `trades` and recomputed `stats`, not an empty list

### Requirement: Persistent alert lifecycle

Alert status transitions (ARMED → TRIGGERED → RESOLVED → re-ARMED) SHALL be persisted to the
database, and a resolved alert whose condition re-crosses SHALL re-arm and be able to fire
again, so restarts do not re-fire duplicate notifications and re-crossings are not permanently
skipped.

#### Scenario: Triggered status survives restart

- **WHEN** an alert fires and the process restarts
- **THEN** the alert's persisted status reflects TRIGGERED/RESOLVED and does not re-fire a duplicate notification for the same crossing

#### Scenario: Resolved alert re-arms on re-cross

- **WHEN** a resolved `PRICE_GT` alert's price drops below and later rises back above the threshold
- **THEN** the alert re-arms and fires again

### Requirement: Bounded background resource lifecycle

Long-running loops SHALL reuse a single database client rather than opening one per cycle, and
SHALL be cleanly cancellable. The options gap-backfill SHALL reuse one `MongoClient` (context-
managed). `DhanTickerAdapter` SHALL use an interruptible wait (cancellable by its stop event)
and its `stop()` SHALL cancel and await the connection task.

#### Scenario: Gap-backfill does not leak clients

- **WHEN** the gap-backfill loop runs repeatedly over a multi-day session
- **THEN** no `MongoClient` is left unclosed across cycles

#### Scenario: Feed adapter shuts down promptly

- **WHEN** the app shuts down while the adapter is in its idle wait
- **THEN** `stop()` interrupts the wait, cancels the connection task, and returns without hanging

### Requirement: Reliable scheduled snapshots

Time-anchored jobs (e.g. the EOD portfolio snapshot) SHALL fire on a "not yet done today and
past the target time" predicate rather than an exact single-minute equality, so clock drift in
the polling loop cannot silently skip a day.

#### Scenario: EOD snapshot survives poll drift

- **WHEN** the polling loop wakes at 15:35:59 and next at 15:37:00, skipping minute 36
- **THEN** the EOD snapshot still fires exactly once that day
