## ADDED Requirements

### Requirement: Event service runs detectors on bar close without blocking the hot path

The system SHALL provide an `EventService` whose `on_bar(bar, snapshot)` is invoked by the `TickRouter` immediately after `IndicatorEngine.on_bar`, runs the configured detector library against the supplied `Snapshot`, and performs no blocking I/O on the calling path. When `EVENTS_ENABLED` is false, `on_bar` SHALL be a no-op. All persistence and push delivery SHALL be performed by background workers fed from an in-memory queue.

#### Scenario: Detectors evaluated on each closed bar
- **WHEN** a 15m bar closes for a watched security and `EVENTS_ENABLED=true`
- **THEN** `EventService.on_bar` runs the spot/indicator detectors against the bar's `Snapshot` and enqueues any produced events for delivery

#### Scenario: Disabled service is a no-op
- **WHEN** `EVENTS_ENABLED=false` and a bar closes
- **THEN** `EventService.on_bar` returns without evaluating detectors and produces no events

#### Scenario: Bar handler never awaits I/O
- **WHEN** a detector produces an event
- **THEN** the Mongo write and any web-push are dispatched via the background queue, not awaited inside `on_bar`

---

### Requirement: Manual Dhan positions are synced and monitored

The system SHALL run a `PositionSync` background loop every `EVENTS_POSITION_SYNC_SECONDS` (default 30) that, in live mode with Dhan credentials, fetches positions via `get_positions()` and otherwise reads the PostgreSQL `positions` table. Each open leg (net_qty ≠ 0) SHALL be represented as a `MonitoredPosition` with security_id, underlying, strike, option_type, expiry, net_qty, avg_price, and side. New legs and their underlying spot SHALL be auto-subscribed to the tick feed; closed legs SHALL be dropped. A Dhan fetch error SHALL retain the last known set and log `position_sync_failed`.

#### Scenario: Manual position picked up and subscribed
- **WHEN** the operator holds a NIFTY 24000 CE position in Dhan and a sync cycle runs in live mode
- **THEN** a `MonitoredPosition` is created for that leg and both the option security_id and the NIFTY spot are subscribed to the tick feed

#### Scenario: Paper-mode fallback to positions table
- **WHEN** Dhan credentials are absent and a sync cycle runs
- **THEN** monitored positions are built from the PostgreSQL `positions` table rows with net_qty ≠ 0

#### Scenario: Sync error is non-fatal
- **WHEN** `get_positions()` raises during a cycle
- **THEN** the previously known monitored set is retained, `position_sync_failed` is logged, and the next cycle retries

---

### Requirement: Detectors run per configured timeframe

The system SHALL evaluate spot/indicator detectors independently for each timeframe in `EVENTS_SPOT_TIMEFRAMES` (default `["5m","15m","30m","1H","1D"]`), so the same condition is reported once per timeframe and each event records its `timeframe`. The system SHALL support a daily (`1D`) timeframe via daily bar aggregation seeded from MongoDB `market_bars`.

#### Scenario: Same condition reported per timeframe
- **WHEN** the 9-EMA crosses the 20-EMA on both the 15m and the 1H series
- **THEN** two `EMA_CROSS` events are emitted, one tagged `timeframe="15m"` and one `timeframe="1H"`

---

### Requirement: Spot and indicator detectors

The system SHALL provide edge-triggered detectors over the universal indicator engine that emit an event exactly once per edge: EMA crossover (configurable pairs incl. 9/20, 9/50, 20/50), price⇄EMA cross, SuperTrend(10,2) direction flip, Parabolic SAR flip, MACD cross, Elder-impulse regime change, Camarilla R3/R4/S3/S4 touch, day-high/low and PDH/PDL break, PWH/PWL/PMH/PML break, configured price-level cross, level-proximity, Fibonacci-level reaction, FVG creation/fill, Elliott-wave label change, RSI extreme/divergence, ML-signal flip. A detector whose required snapshot family is absent SHALL return no event and SHALL NOT raise.

#### Scenario: SuperTrend flip on a timeframe
- **WHEN** the SuperTrend(10,2) direction flips from up to down on the 15m series
- **THEN** a single `SUPERTREND_FLIP` event is emitted for that timeframe

#### Scenario: EMA crossover fires once per cross
- **WHEN** the 50-EMA crosses above the 20-EMA on the watched timeframe
- **THEN** a single `EMA_CROSS` event is emitted and no further `EMA_CROSS` event is emitted until the relationship inverts again

#### Scenario: Missing family does not raise
- **WHEN** no ML model is loaded and a bar closes
- **THEN** the ML-signal-flip detector returns no event and raises no exception

---

### Requirement: Position MTM, OTM-distance, and safe-to-exit detectors

The system SHALL provide position-aware detectors: an MTM-swing event when a monitored position's mark-to-market moves by at least `EVENTS_MTM_SWING_INR` since the last emission; an OTM-distance event when the underlying spot comes within `EVENTS_OTM_DISTANCE_PTS` of a held OTM strike; a trailing safe-to-exit event when open MTM retraces by at least `EVENTS_TRAIL_GIVEBACK_PCT` from its session peak; and a momentum safe-to-exit event when momentum turns against the position (Parabolic SAR flip together with a price⇄EMA(50) cross in the adverse direction).

#### Scenario: OTM distance breach
- **WHEN** the operator holds a NIFTY 24000 OTM CE, `EVENTS_OTM_DISTANCE_PTS=100`, and spot rises to 23905
- **THEN** an `OTM_DISTANCE` event is emitted reporting spot is within ~95 pts of the 24000 strike

#### Scenario: Trailing giveback safe-to-exit
- **WHEN** a position's MTM peaks at +10000 and retraces to +6900 with `EVENTS_TRAIL_GIVEBACK_PCT=30`
- **THEN** a `SAFE_TO_EXIT_TRAIL` event is emitted

#### Scenario: Momentum reversal safe-to-exit
- **WHEN** the operator is long a CE and PSAR flips bearish and price crosses below EMA(50)
- **THEN** a `SAFE_TO_EXIT_MOMENTUM` event is emitted, distinct from any `SAFE_TO_EXIT_TRAIL` event

---

### Requirement: Confluence-zone detector

The system SHALL emit a `CONFLUENCE_ZONE` event when at least `EVENTS_CONFLUENCE_MIN` (default 2) distinct level-sources — drawn from period levels (PDH/PDL/PWH/PWL/PMH/PML), pivots/Camarilla, Fibonacci levels, FVG edges, EMAs, VWAP, and OI walls — cluster within `EVENTS_CONFLUENCE_BAND_PTS` of the current price. The event payload SHALL list which sources aligned, and its severity SHALL increase with the number of aligned sources.

#### Scenario: Multiple sources align near price
- **WHEN** spot is 23600 and the 1H 50-EMA, an unfilled FVG edge, and a Fibonacci level all sit within 25 pts, with `EVENTS_CONFLUENCE_MIN=2`
- **THEN** a `CONFLUENCE_ZONE` event is emitted listing the three aligned sources

---

### Requirement: OI, PCR, GEX, and IV detectors

The system SHALL provide detectors driven by option-chain refreshes: `OI_BUILDUP` when OI at a held strike rises by `EVENTS_OI_BUILDUP_PCT`, `PCR_SHIFT` when PCR crosses a band in `EVENTS_PCR_BANDS`, `GEX_WALL` when spot comes within `EVENTS_GEX_WALL_PTS` of the largest-magnitude GEX strike, `OI_WALL` identifying OI S/R strikes + rejection, `MAX_PAIN_PIN` when max-pain shifts or spot pins near expiry, and `IV_SHIFT` when implied volatility spikes or crushes beyond a threshold. These SHALL reuse `compute_pcr`, `compute_gex`, `compute_max_pain` from `options/analytics.py`.

#### Scenario: OI build-up at a held strike
- **WHEN** OI at the operator's held 24000 CE rises 25% over the chain window and `EVENTS_OI_BUILDUP_PCT=20`
- **THEN** an `OI_BUILDUP` event is emitted for that strike

#### Scenario: PCR crosses band
- **WHEN** `EVENTS_PCR_BANDS=[0.7, 1.3]` and PCR moves from 1.25 to 1.34
- **THEN** a `PCR_SHIFT` event is emitted naming the crossed band edge (1.3)

---

### Requirement: Portfolio Greeks and delta-neutral drift detector

The system SHALL emit a `DELTA_NEUTRAL_DRIFT` event when the net aggregate delta across monitored option positions leaves the neutral band `EVENTS_DELTA_NEUTRAL_BAND`, computed from chain Greeks for held strikes. The system SHALL emit a `BREAKEVEN_BREACH` event when spot breaches the computed breakeven of a multi-leg position.

#### Scenario: Delta drifts from neutral
- **WHEN** a delta-neutral strangle's aggregate delta drifts to +0.20 net and `EVENTS_DELTA_NEUTRAL_BAND=0.15`
- **THEN** a `DELTA_NEUTRAL_DRIFT` event is emitted reporting the net delta and direction

---

### Requirement: Portfolio stats digest

The system SHALL emit a `PORTFOLIO_STATS` event every `EVENTS_STATS_INTERVAL_SECONDS` (default 300) summarising the trading session: number of trades, total premium received, realized + unrealized P&L, max profit, and max loss, sourced from the existing journal and portfolio services.

#### Scenario: Stats digest emitted
- **WHEN** `EVENTS_STATS_INTERVAL_SECONDS=300` elapses during a session with open positions
- **THEN** a `PORTFOLIO_STATS` event is emitted with trade count, premium received, P&L, max profit, and max loss

---

### Requirement: Event de-duplication and cooldown

The system SHALL de-duplicate events so that a condition which remains true does not emit repeatedly. Each `(security_id, detector, level-key)` SHALL carry a state that transitions to fired on the triggering edge and clears when the condition releases, and SHALL NOT re-emit the same key within `EVENTS_COOLDOWN_SECONDS` (default 300).

#### Scenario: Sustained condition does not spam
- **WHEN** the close stays above cam_r4 for ten consecutive bars
- **THEN** exactly one `CAMARILLA_TOUCH` event for that level is emitted, not ten

#### Scenario: Re-arm after release
- **WHEN** the close falls back below cam_r4 and later crosses it again after the cooldown
- **THEN** a new `CAMARILLA_TOUCH` event is emitted

---

### Requirement: Event persistence and history endpoint

The system SHALL persist every emitted event to the MongoDB `events` collection with a TTL of `EVENTS_TTL_DAYS` (default 14) and SHALL expose `GET /api/v1/events` returning recent events newest-first, filterable by `security_id`, `event_type`, and `severity`, with a `limit` (default 100).

#### Scenario: Event persisted and retrievable
- **WHEN** a `PSAR_FLIP` event is emitted and `GET /api/v1/events?event_type=PSAR_FLIP` is called
- **THEN** the response includes that event with its title, message, payload, and UTC timestamp

---

### Requirement: WebSocket event delivery

The system SHALL expose `/ws/events` that streams events to connected clients in real time, backfills the most recent events on connect, and uses a bounded per-client queue that drops the oldest message when full (never blocking the publisher).

#### Scenario: Live event pushed to WS client
- **WHEN** a client is connected to `/ws/events` and an event is emitted
- **THEN** the event JSON is delivered to that client without blocking the `EventService`

#### Scenario: Backfill on connect
- **WHEN** a client connects to `/ws/events`
- **THEN** it immediately receives the most recent events before live streaming begins

---

### Requirement: Web Push delivery with subscription management

The system SHALL deliver events at or above `EVENTS_PUSH_MIN_SEVERITY` (default WARNING) to registered browsers via Web Push (VAPID) when `EVENTS_PUSH_ENABLED` is true. The system SHALL expose `GET /api/v1/events/push/vapid-key` returning the public VAPID key and `POST /api/v1/events/push/subscribe` persisting a subscription to the `push_subscriptions` PostgreSQL table. Subscriptions returning 404/410 on send SHALL be pruned.

#### Scenario: Push sent for high-severity event
- **WHEN** `EVENTS_PUSH_ENABLED=true`, a browser is subscribed, and a `CRITICAL` event is emitted
- **THEN** a Web Push notification is sent to that subscription

#### Scenario: Low-severity event not pushed
- **WHEN** `EVENTS_PUSH_MIN_SEVERITY=WARNING` and an `INFO` event is emitted
- **THEN** no Web Push is sent, but the event still appears in the in-app feed

#### Scenario: Expired subscription pruned
- **WHEN** a Web Push send returns HTTP 410 for a subscription
- **THEN** that subscription row is deleted from `push_subscriptions`

### Requirement: Expanded event type wiring

The events service SHALL wire at minimum: `order_fill` (emitted by `OrderRouter` on fill), `sl_hit` (emitted by strategy/risk on stop-loss trigger), `target_hit` (emitted on target trigger), `margin_warning` (emitted when daily P&L approaches `RISK_DAILY_LOSS_CAP_INR`), `strategy_signal` (emitted on strategy signal generation), and `kill_switch_triggered` (emitted by `KillSwitchService`). Each wired type SHALL call `event_service.emit()` at the appropriate call site.

#### Scenario: Order fill event emitted
- **WHEN** a paper order is filled by the PaperBroker
- **THEN** an event of type `order_fill` with severity `info` is emitted with the order ID, symbol, side, quantity, and fill price

#### Scenario: Kill switch event emitted
- **WHEN** `KillSwitchService` activates and closes all positions
- **THEN** a `kill_switch_triggered` event with severity `critical` is emitted
