## ADDED Requirements

### Requirement: Broker sync SHALL be enabled by default and remain credential-gated

`BROKER_SYNC_ENABLED` SHALL default to `true` so the broker's holdings, positions and funds are
mirrored without operator action. The subsystem SHALL remain read-only with respect to the broker
(no order placement) and SHALL remain credential-gated: when Dhan credentials are absent the run is
recorded with status `skipped` and startup SHALL NOT fail.

#### Scenario: Credentials present

- **WHEN** the app starts with `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` set
- **THEN** `BrokerSyncService`, the EOD scheduler and the intraday poller are constructed and started

#### Scenario: Credentials absent

- **WHEN** the app starts with no Dhan credentials
- **THEN** a run is recorded with status `skipped`, no exception propagates, and the app serves traffic

#### Scenario: Broker sync places no orders

- **WHEN** any broker-sync code path executes
- **THEN** it issues only read-only broker report calls and never submits, modifies or cancels an order

### Requirement: The intraday poller SHALL refresh current state only, never perform daily archival

`BrokerIntradayPoller` SHALL call a dedicated `refresh_state()` that fetches holdings, positions and
funds, replaces the PostgreSQL mirror, and re-subscribes the market feed. It SHALL NOT write a
`BrokerSyncRun` audit row, SHALL NOT upsert the Mongo daily snapshot, SHALL NOT fetch orders, trades
or ledger, and SHALL NOT run reconciliation. The poller SHALL run only during market hours
(09:15–15:30 IST) and SHALL skip silently when credentials are absent.

#### Scenario: A single intraday poll

- **WHEN** the poller fires at 11:00 IST with credentials configured
- **THEN** exactly three broker report calls are made (holdings, positions, funds), the PG mirror is
  replaced, and no `BrokerSyncRun` row and no `broker_snapshots` document are written

#### Scenario: Poll outside market hours

- **WHEN** the poller loop wakes at 16:30 IST
- **THEN** no broker call is made and the loop sleeps until the next interval

#### Scenario: Mongo snapshot reflects end of day

- **WHEN** the EOD sync has run at 15:45 IST after a full session of intraday polling
- **THEN** the `broker_snapshots` document for that date holds the EOD state, written exactly once by
  the EOD run

### Requirement: The EOD archival SHALL NOT be pre-empted by intraday activity

`already_succeeded(snapshot_date)` SHALL consider only runs whose trigger is `auto` or `manual`.
Runs recorded with any intraday trigger SHALL NOT satisfy the idempotency check that guards the
scheduled EOD archival.

#### Scenario: EOD fires after a full day of polling

- **WHEN** the scheduler evaluates its condition at 15:45 IST and the day contains only intraday-origin activity
- **THEN** `already_succeeded` returns `false` and the EOD `run_daily` executes

#### Scenario: EOD remains idempotent

- **WHEN** the scheduler evaluates its condition again at 15:46 IST and an `auto` run already completed `ok` for that date
- **THEN** `already_succeeded` returns `true` and no second archival runs

### Requirement: Position reconciliation SHALL run only when the platform routes orders to the live broker

Reconciliation SHALL execute only when `LIVE` is true and `BROKER` is `dhan`, covering both the
in-run `_reconcile` comparison and `reconcile_day_positions`, each of which compares PostgreSQL
`Position` rows against broker positions. In paper mode the run SHALL record `recon` as skipped with reason `paper_mode`
and SHALL emit no `POSITION_RECONCILE_MISMATCH` event and no mismatch warning. Reconciliation SHALL
remain read-only in all modes and SHALL NOT mutate `Position` rows.

#### Scenario: Paper mode

- **WHEN** a daily sync completes with `LIVE=false` and open paper positions exist
- **THEN** no `POSITION_RECONCILE_MISMATCH` event is emitted and the run's `recon` records reason `paper_mode`

#### Scenario: Live mode with a genuine mismatch

- **WHEN** `LIVE=true`, `BROKER=dhan`, and internal net qty for a security differs from the broker's
- **THEN** one `POSITION_RECONCILE_MISMATCH` critical event is emitted for that security and no `Position` row is modified

#### Scenario: Live mode in agreement

- **WHEN** `LIVE=true`, `BROKER=dhan`, and every security's internal net qty equals the broker's
- **THEN** no event is emitted and the run's `recon` reports zero mismatches

### Requirement: Broker-sync read endpoints SHALL distinguish a disabled subsystem from an empty account

`GET /holdings`, `/positions` and `/funds` SHALL return **503** with detail `broker sync not enabled`
when the service is not constructed, rather than an empty `200` page. A new
`GET /api/v1/broker-sync/status` SHALL report `enabled`, `has_credentials`, `live_mode`,
`last_state_refresh_at` and the most recent archival run, so a client can tell apart: subsystem
disabled, credentials missing, enabled but never synced, and enabled with a genuinely empty
account. Because the intraday path writes no run row, `last_state_refresh_at` — not `last_run` —
SHALL be the mirror-freshness signal.

#### Scenario: Subsystem disabled

- **WHEN** a client calls `GET /api/v1/broker-sync/positions` while `BROKER_SYNC_ENABLED` is false
- **THEN** the response is 503 with detail `broker sync not enabled`

#### Scenario: Enabled but never synced

- **WHEN** the service is constructed, no refresh or archival has run, and a client calls `GET /positions`
- **THEN** the response is an empty 200 page, and `GET /status` reports `enabled: true` with a null
  `last_state_refresh_at`

#### Scenario: Enabled with a flat account

- **WHEN** a refresh has populated the mirror and the broker holds no positions
- **THEN** `GET /positions` returns an empty 200 page and `GET /status` reports a non-null `last_state_refresh_at`

#### Scenario: Client can distinguish the four states

- **WHEN** the app renders the manage screen
- **THEN** it shows a distinct state for disabled, missing credentials, never-run, and empty account — never a bare empty list for the first three

### Requirement: Snapshot dates SHALL be the IST calendar date

`run_daily` SHALL derive its default `snapshot_date` from the current Asia/Kolkata calendar date, so
that a run triggered at any hour is filed under the Indian trading day and agrees with the date the
EOD scheduler passes explicitly.

#### Scenario: Early-morning manual run

- **WHEN** a manual sync is triggered at 01:00 IST on 2026-07-10 (19:30 UTC on 2026-07-09)
- **THEN** the snapshot date is `2026-07-10`, not the UTC date `2026-07-09`

#### Scenario: Scheduler and default agree

- **WHEN** the EOD scheduler fires at 15:45 IST and passes an explicit date
- **THEN** that date equals what `run_daily` would have derived on its own

### Requirement: Application startup SHALL fail loudly when a live-trading runtime group cannot start

The lifespan handler SHALL re-raise start-up exceptions from runtime groups that carry live-trading
responsibility, rather than logging `group_start_failed` and continuing. Non-critical groups
(observability, dashboard intel) MAY retain fault-isolated start-up.

#### Scenario: A live-trading group fails to start

- **WHEN** a group responsible for broker sync, market feed, strategy host or order routing raises during `start`
- **THEN** the exception propagates, the application does not begin serving traffic, and the failure is logged

#### Scenario: A non-critical group fails to start

- **WHEN** an observability or intel group raises during `start`
- **THEN** the failure is logged, the remaining groups start, and the application serves traffic
