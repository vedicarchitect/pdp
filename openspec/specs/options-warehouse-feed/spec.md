# options-warehouse-feed Specification

## Purpose

Standalone live NIFTY options warehousing service that streams option bars independently of the
trading application, keeps a rolling ATM±10 current/next-week strike band subscribed, self-heals
coverage gaps, and gates the realtime options-chain poller so paper sessions get Greeks/OI/PCR data.

## Requirements

### Requirement: Standalone live options warehouser service

The system SHALL provide a standalone process (`python -m pdp.warehouse`) that streams NIFTY option
bars into `option_bars` independently of the trading application. The service MUST own its own
market-feed connection and subscription set, and MUST persist 1-minute bars tagged `source=live`
through the contract-aware upsert writer.

#### Scenario: Service starts and streams

- **WHEN** the warehouser starts during market hours
- **THEN** it connects to the Dhan market feed and begins building 1-minute bars from ticks
- **AND** each closed bar is upserted into `option_bars` as a fixed-strike contract with a resolved
  `expiry_date`, `strike`, `option_type`, and `trading_symbol`

---

### Requirement: Current/next-week ATM±10 band with daily roll

The service SHALL maintain a subscription band of the **current weekly + next weekly** expiries
(monthly optional), each spanning **ATM±10** strikes for both `CE` and `PE`. It MUST recompute the
band at session start and on ATM or expiry roll, resolving each strike to a `security_id` via the
instruments table / masters snapshot.

#### Scenario: Band computed at session start

- **WHEN** the daily roll runs
- **THEN** the service determines the current and next weekly expiry dates from the expiry calendar
- **AND** builds the ATM±10 × {CE, PE} strike set per expiry from the current spot
- **AND** subscribes the resolved `security_id`s for those contracts plus the NIFTY index

#### Scenario: Band rolls when ATM or expiry changes

- **WHEN** spot moves enough to shift ATM, or the current weekly expires
- **THEN** the service updates its subscriptions to the new band without restarting the process

---

### Requirement: Masters snapshot for symbol/id recovery

At session start the service SHALL ensure a daily masters snapshot
(`data/masters/<YYYY-MM-DD>.csv`) exists so that expired contracts' `trading_symbol` and historical
`security_id` remain recoverable for later fixed-contract fetches.

#### Scenario: Snapshot ensured at start

- **WHEN** the warehouser starts on a trading day
- **THEN** a masters snapshot for that day exists (created if absent)

---

### Requirement: Single writer for forward spot

The warehouser SHALL be the single writer of forward NIFTY index 1-minute bars into `market_bars`
(security_id `13`), so that two producers cannot create duplicate spot bars in the time-series
collection.

#### Scenario: Spot captured once

- **WHEN** the warehouser streams the NIFTY index
- **THEN** index 1-minute bars are written to `market_bars` exactly once per `ts`

---

### Requirement: Periodic self-healing gap backfill

While running, the warehouser SHALL periodically scan a rolling look-back window
(`WAREHOUSE_GAP_LOOKBACK_DAYS`, default 30 days) for trade-days whose `option_bars` coverage is
below the expected band, and automatically backfill the missing days from Dhan. The check MUST run
on a configurable interval (`WAREHOUSE_GAP_CHECK_INTERVAL_HOURS`, default 4 hours) and MUST NOT block
the live tick/bar hot path. Backfilled bars use the same first-write-wins upsert, so re-filling an
already-covered day is non-duplicate. The feature MUST be toggleable via
`WAREHOUSE_GAP_BACKFILL_ENABLED` and MUST share the gap-fill core with the one-shot backfill script.

#### Scenario: Missing day detected and backfilled

- **WHEN** a periodic gap check finds a trade-day in the look-back window with fewer than the
  expected number of distinct contracts in `option_bars`
- **THEN** the warehouser fetches that day's band from Dhan and upserts the fixed-strike bars
- **AND** a fully-covered day is left untouched (no duplicate writes)

#### Scenario: Gap check never blocks the live feed

- **WHEN** a gap-backfill cycle runs (blocking Dhan REST + pymongo work)
- **THEN** it executes off the event loop (worker thread) so tick consumption and bar writing
  continue uninterrupted

---

### Requirement: Options chain poller start condition

The options chain poller SHALL start whenever `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN` are present and
`OPTIONS_POLLER_ENABLED` is true, independent of the `LIVE` flag, so that paper sessions receive realtime
chain data (Greeks, OI, PCR). The poller is read-only market data and MUST NOT place or modify orders.
When credentials are absent or `OPTIONS_POLLER_ENABLED` is false, the poller SHALL NOT start and chain
REST endpoints SHALL return an empty `{"mode":"paper"}` snapshot.

#### Scenario: Poller runs in paper with credentials

- **WHEN** `LIVE` is unset but `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` are set and `OPTIONS_POLLER_ENABLED` is true
- **THEN** the options poller starts and persists `option_chains` snapshots during market hours

#### Scenario: Poller disabled by flag

- **WHEN** `OPTIONS_POLLER_ENABLED` is false
- **THEN** the poller does not start regardless of credentials

#### Scenario: Poller skipped without credentials

- **WHEN** `DHAN_CLIENT_ID` or `DHAN_ACCESS_TOKEN` is absent
- **THEN** the poller does not start and `GET /api/v1/options/NIFTY/chain` returns `{"mode":"paper", ...}`
