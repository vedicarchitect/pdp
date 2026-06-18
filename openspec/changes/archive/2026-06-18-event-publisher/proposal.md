## Why

The operator holds **manual** positions in the Dhan account (placed outside this app). Because the broker requires IP-whitelisting for order placement, the platform cannot act on those positions automatically — but it already ingests the live tick feed, computes a 14-family indicator suite + ML signals once per bar, and polls the option chain for OI/Greeks. Today none of that intelligence reaches the operator as actionable, real-time signal; the existing `alerts/` engine only supports static price/Greeks/PnL thresholds on a single security and only delivers to an in-app WebSocket that must be open.

This change adds a **live event-publisher**: a continuously-running monitor that watches the operator's held positions and the underlying market, runs a library of detectors over the universal indicator engine + option analytics, and publishes de-duplicated realtime events to an in-app feed **and** browser/desktop push (so they arrive even when the UI is closed). It is alerts-only — it never places orders.

## What Changes

- **New `events/` module** with an `EventService` that runs detectors on every closed bar (hot path), on position MTM updates, and on each option-chain refresh; de-duplicates via a per-key state machine + cooldown; persists to MongoDB; and fans out to delivery channels.
- **Position sync**: a background loop polls Dhan `get_positions()` (falls back to the PostgreSQL `positions` table in paper mode), builds a `MonitoredPosition` set (strike/expiry/option-type/qty/avg), auto-subscribes each leg + its underlying spot to the tick feed, and tracks a per-position MTM peak for trailing-exit detection.
- **Detector library** over the existing `IndicatorEngine` / `IndicatorReader` + `options/analytics.py`, each run **per configured timeframe** (default 5m/15m/30m/1H/1D). Grouped into five families (full table in `design.md`):
  - *A. Levels & confluence*: custom price-level cross (23600/24000…), level-proximity, and a **confluence-zone** detector that fires when ≥N level-sources (FVG, fib, Elliott swing, EMA, VWAP, pivots, OI wall) cluster within a band of price.
  - *B. Trend/momentum*: EMA crossovers (9/20, 9/50, 20/50), price⇄EMA cross, **SuperTrend(10,2) flip on any TF**, PSAR flip, MACD cross, Elder-impulse change, Elliott wave, ML-signal flip, RSI extreme/divergence.
  - *C. Range/breakout/volume*: day-H/L · PDH/PDL · PWH/PWL · PMH/PML breaks, **custom strangle-range break**, **volume spike** (futures z-score), volume-profile S/R rejection, **gap up/down** at open.
  - *D. Options/OI/Greeks*: **OI wall** S/R + rejection, OI build-up/unwind, **OI volume spike**, PCR shift, GEX wall, **max-pain pin/shift**, **IV spike/crush**, **portfolio delta-neutral drift**, **breakeven breach**, expiry countdown.
  - *E. Position/P&L/portfolio*: MTM swing, OTM-distance, two safe-to-exit events (trailing-MTM giveback + momentum reversal), leg-stop proximity, directional-trade critical-junction, **portfolio-stats digest** (# trades, premium received, P&L, max profit/loss), and position-change (open/close) events.
- **New `period_levels` indicator family** for PWH/PWL/PMH/PML (previous-week / previous-month high-low), seeded from MongoDB `market_bars`. (PDH/PDL already exist as `PivotState.prior_h/prior_l`.)
- **Delivery channels**: `EventsHub` WebSocket (`/ws/events`) + Web Push (VAPID) to registered browsers/desktops via a new `push_subscriptions` table and a frontend service worker.
- **Frontend**: a new `/events` route with a live, filterable event feed, plus push-subscription enrolment and an unread badge in the sidebar.

## Capabilities

### New Capabilities
- `event-publisher`: position sync, detector library, event de-duplication + persistence, WebSocket + Web Push delivery, REST history/config endpoints, and the frontend event feed.

### Modified Capabilities
- `indicator-suite`: adds the `period_levels` family (PWH/PWL/PMH/PML) to the universal engine, snapshot, registry, warmup, and `IndicatorReader`.

## Impact

- New module `src/pdp/events/` — `models.py`, `service.py`, `detectors/` (levels, trend, range_volume, oi_greeks, position, portfolio), `positions.py` (Dhan position sync), `hub.py` (WS), `push.py` (Web Push), `store.py` (Mongo), `routes.py`.
- `src/pdp/market/bars.py` + warmup — add `1D` (daily) bar aggregation so daily EMA / level / SuperTrend detectors work.
- Portfolio-stats digest reads the existing `JournalService` / `PortfolioService` (# trades, premium received, P&L, max profit/loss); delta-neutral drift aggregates per-position delta from the Dhan positions feed + chain Greeks.
- New `src/pdp/indicators/period_levels.py` + registry/snapshot/engine/warmup/`IndicatorReader` wiring.
- `src/pdp/market/router.py` — pass `event_service` and call `event_service.on_bar(bar, snapshot)` after `IndicatorEngine.on_bar` (hot path, non-blocking).
- `src/pdp/settings.py` — event thresholds, watched price levels, OTM distance, MTM/trailing thresholds, OI/PCR thresholds, sync interval, VAPID keys, push toggle.
- `src/pdp/main.py` — start `EventService` + `PositionSync`, wire into `TickRouter`, subscribe to `OptionsHub`, register `/api/v1/events` router + `/ws/events`.
- New PostgreSQL table `push_subscriptions` (Alembic migration); new MongoDB `events` collection (TTL).
- `frontend/` — new `routes/events.tsx`, `components/events/*`, `public/sw.js` service worker, push-enrol hook, sidebar badge.
- New dependency `pywebpush` (Web Push delivery).
- Tests: `tests/events/` (detectors, dedup, position sync) and `tests/indicators/test_period_levels.py`.
