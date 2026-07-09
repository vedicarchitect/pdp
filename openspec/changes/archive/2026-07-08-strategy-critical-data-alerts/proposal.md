# strategy-critical-data-alerts

## Why

Today, when a strategy or the live engine hits **missing or degraded data**, it proceeds
silently or only `log.warning`s — the trader never finds out until money is at risk. The
whole-backend review found concrete cases:

- **Naked position (C5)** — `_open_hedge`/`_open_momentum` read an option's LTP immediately
  after subscribing it; on a cold `ltp:<sid>` cache the hedge scan finds no priced instrument,
  logs `hedge_no_instrument`, and **leaves the short legs completely unhedged** (or sizes
  momentum to 1 lot instead of ~₹50k). No alert reaches the trader.
- **Unseeded opening range (C9)** — after an intraday restart the ORB is captured from the
  first 15m bar the process happens to see (e.g. 11:45–12:00) instead of the true 09:15–09:30
  window, so the bias votes off a bogus range all day — a silent live/backtest parity break.
- **Incomplete warmup** — insufficient warmup (e.g. EMA200 shows `--`) currently just logs;
  strategies can arm on an under-seeded engine and diverge from the backtest.
- **Stale feed** — `FeedWatchdog`/`FeedStaleHalt` already halt trading but do not surface a
  first-class CRITICAL alert.
- **Swallowed failures** — several `except Exception: log.warning(...)` blocks on money/data
  paths hide failures instead of surfacing them.

The `events/` pipeline (Mongo `events` + `/ws/events` + Web Push, with `Severity.CRITICAL`
already defined) is the right place to surface all of these. This change adds one reusable
"emit critical" path and wires the missing-data guards to it, and tightens exception handling so
failures become CRITICAL events rather than silent logs.

## What Changes

- **New `EventType`s:** `WARMUP_INCOMPLETE`, `MISSING_LTP`, `NAKED_POSITION`, `FEED_STALE`,
  `INDICATOR_UNSEEDED`, `EXCEPTION_CRITICAL` (added to `events/models.py`).
- **One reusable emit helper** — `EventService.emit_critical(event_type, security_id, title,
  message, payload)` (single-responsibility; routes through the existing dedup/cooldown `emit`
  gate → `EventsHub` + `EventStore` + Web Push). Exposed to strategies via `StrategyContext`
  (`ctx.emit_critical(...)`), so no strategy constructs `Event`s directly.
- **Missing-data guards (do the safe thing AND alert):**
  - Naked hedge — if no wing is priced, retry-with-bounded-wait for a tick; if still unpriced,
    square the just-opened short and `emit_critical(NAKED_POSITION, ...)` instead of holding a
    silent naked short.
  - Unseeded ORB — detect that ORB was not seeded from the real opening window and
    `emit_critical(INDICATOR_UNSEEDED, ...)`; do not vote off a bogus range.
  - Warmup incomplete — keep strategies **disarmed** until the engine is sufficiently seeded and
    `emit_critical(WARMUP_INCOMPLETE, ...)` (complements the non-blocking-warmup design in the
    worker-decoupling change).
  - Feed stale — wire `FeedWatchdog`/`FeedStaleHalt` to `emit_critical(FEED_STALE, ...)`.
- **VIX-gate correctness (C13)** — feed the gate 5m-candle VIX values and a 09:15 day-open
  baseline (matching the backtest) instead of raw sub-second ticks and a first-tick baseline.
- **Exception hardening** — money/data-path `except Exception: log.warning(...)` blocks either
  re-raise or `emit_critical(EXCEPTION_CRITICAL, ...)`; broad/bare excepts remain only in
  top-level boundaries and teardown.

## Impact

- **Affected specs:** `strategy-critical-data-alerts` (new — the emit-critical contract + the
  missing-data guard requirements), `directional-strangle` (naked-hedge / ORB / VIX behaviour),
  `indicator-warmup` (disarm-until-seeded), `feed-health` (feed-stale critical event).
- **Affected code:** `backend/pdp/events/models.py`, `events/service.py`,
  `strategy/context.py`, `strategies/directional_strangle.py`, `indicators/warmup.py`,
  `market/router.py` / feed watchdog, and the money/data-path `except` blocks flagged by the
  review.
- **Flutter:** the existing event-feed already renders `/ws/events`; the new CRITICAL types get
  a Dart enum entry + icon (`app/lib/features/events/`). No new screen.
- **Reuses:** `EventService.emit` (dedup/cooldown), `EventsHub`, `EventStore`, `WebPushSender`,
  `Severity.CRITICAL`, `FeedWatchdog`. Adds no new external dependency, no new datastore.
- **Depends on:** none structurally; complements change #1 (which un-swallows the failures) and
  change #3 (non-blocking warmup). Can ship in parallel with #1.
