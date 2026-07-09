## ADDED Requirements

### Requirement: Reusable critical-event emit path

`EventService` SHALL expose a single `emit_critical(event_type, security_id, title, message,
payload)` method that constructs a `Severity.CRITICAL` `Event` and routes it through the existing
dedup/cooldown `emit` gate to the WebSocket hub, the Mongo `events` store, and Web Push.
Strategies SHALL emit critical alerts only through `StrategyContext.emit_critical(...)` and SHALL
NOT construct `Event`s directly. The new event types `WARMUP_INCOMPLETE`, `MISSING_LTP`,
`NAKED_POSITION`, `FEED_STALE`, `INDICATOR_UNSEEDED`, and `EXCEPTION_CRITICAL` SHALL be defined.

#### Scenario: Critical event reaches all sinks

- **WHEN** `emit_critical(NAKED_POSITION, ...)` is called
- **THEN** a `CRITICAL` event is published to `/ws/events`, persisted to the Mongo `events` collection, and delivered via Web Push (subject to min-severity config)

#### Scenario: Duplicate critical condition is de-duplicated

- **WHEN** the same critical condition (same `dedup_key`) recurs within the cooldown window
- **THEN** it is not re-published until the cooldown elapses

### Requirement: No silent naked position

A strategy SHALL NOT leave a short leg unhedged silently when the intended hedge cannot be
priced. When no hedge wing has a usable LTP, the strategy SHALL retry within a bounded wait for a
tick, and if the hedge still cannot be priced SHALL square the just-opened short (or otherwise
avoid the naked exposure) AND emit a `NAKED_POSITION` critical event.

#### Scenario: Cold hedge cache does not leave a naked short

- **WHEN** the short legs open but every candidate hedge wing has a cold `ltp:` cache
- **THEN** the strategy does not hold a silent naked short — it squares the exposure and emits a `NAKED_POSITION` critical event

### Requirement: Unseeded indicator does not drive decisions

A strategy SHALL detect when a session-scoped indicator (e.g. the opening range) was not seeded
from its true source window and SHALL emit an `INDICATOR_UNSEEDED` critical event rather than
voting off an incorrectly-derived value.

#### Scenario: Mid-session restart does not vote off a bogus opening range

- **WHEN** the strategy restarts intraday and the opening range was not captured from the real 09:15–09:30 window
- **THEN** it emits `INDICATOR_UNSEEDED` and does not feed the bogus range into the bias vote

### Requirement: Strategies stay disarmed until warmup is sufficient

The system SHALL keep strategies disarmed until the `IndicatorEngine` is sufficiently warmed for
the timeframes they consume, and SHALL emit a `WARMUP_INCOMPLETE` critical event when warmup is
insufficient at the point a strategy would otherwise arm.

#### Scenario: Under-seeded engine blocks arming

- **WHEN** a strategy would arm but a required indicator (e.g. EMA200 on a consumed timeframe) is not seeded
- **THEN** the strategy remains disarmed and a `WARMUP_INCOMPLETE` critical event is emitted

### Requirement: Feed staleness raises a critical event

The feed watchdog SHALL emit a `FEED_STALE` critical event when it detects the market feed has
gone stale (in addition to any trading halt it already performs).

#### Scenario: Stale feed alerts the trader

- **WHEN** the feed watchdog detects staleness beyond its threshold
- **THEN** a `FEED_STALE` critical event is published alongside the halt

### Requirement: VIX gate uses candle-based inputs

The VIX gate SHALL be fed 5-minute VIX candle values and a session-open (09:15) baseline that
match the backtest, rather than raw sub-second ticks and a first-tick baseline, so the gate
behaves identically live and in backtest.

#### Scenario: Gate compares 5m candles, not ticks

- **WHEN** the VIX gate evaluates its "rising over the last 3 candles" and "% above day-open" conditions
- **THEN** it uses 5-minute candle values and the 09:15 day-open baseline, not consecutive sub-second ticks

### Requirement: Money and data-path failures surface as events

Exception handlers on money and data paths SHALL NOT silently swallow failures; they SHALL either
re-raise or emit an `EXCEPTION_CRITICAL` event. Broad or bare `except` clauses are permitted only
in top-level error boundaries and teardown code.

#### Scenario: Swallowed money-path error becomes a critical event

- **WHEN** an exception occurs on a money/data path that previously only `log.warning`ed
- **THEN** the failure is re-raised or surfaced as an `EXCEPTION_CRITICAL` event, not hidden
