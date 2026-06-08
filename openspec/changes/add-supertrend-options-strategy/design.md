# Design

## SuperTrend indicator (universal)

`pdp/indicators/supertrend.py` holds a pure `SuperTrendTracker` (Wilder ATR, O(1)/bar) and a
`supertrend(...)` batch helper. `pdp/indicators/engine.py` `IndicatorEngine` keeps one tracker
per `(security_id, timeframe)` and is driven by `TickRouter` on each `BarClosed` — **before**
the strategy-host dispatch so strategies read the fresh value for that bar. Latest state is
also cached in Redis `st:<sid>:<tf>` for observability. Strategies read via
`ctx.indicators.supertrend(sid, tf) -> SuperTrendState(direction, value, flipped, bar_time)`;
they never recompute (rule #4).

Direction: `+1` uptrend (green), `-1` downtrend (red). `None` until ATR seeds (`period` bars).

## Strike resolution

`pdp/strategy/strikes.py`:
- `nearest_weekly_expiry(session, underlying)` → min `instruments.expiry >= today (IST)`.
- `resolve_otm_option(session, underlying, spot, option_type, otm_steps, strike_step)` →
  round spot to `strike_step` (NIFTY 50), shift OTM (PE below / CE above), look up the
  `Instrument` row. Returns `None` when the instrument table lacks the row.

## Context extensions

`StrategyContext` gains optional `indicators`, `market`, and `session_maker`.
`IndicatorReader` wraps `IndicatorEngine.get`; `MarketControl` wraps the Dhan adapter's
existing runtime `subscribe`/`unsubscribe` (a no-op when no live feed). `StrategyHost` gets
`set_indicator_engine()` / `set_market_adapter()` setters wired in `main.py`.

## Strategy logic (`pdp/strategies/supertrend_short.py`)

Driven by `on_bar` on the NIFTY 5m bar. Schedule lives in YAML `params` (`start_ist`,
`square_off_ist`) parsed against `Asia/Kolkata`. State: last direction, current leg
`{security_id, segment, option_type, strike, lots}`, subscribed set, done-for-day flag.

- Subscribe the index feed in `on_init` (so bars flow).
- Per 5m bar (deduped by `bar_time`): if `now >= square_off` → flatten + stop; if
  `now < start` → only track direction; else act on `ctx.indicators.supertrend`.
- Desired option = PE if up else CE. No leg → open `start_lots`. Leg side ≠ desired →
  close + reopen `start_lots`. Same side → add `add_lots` up to `max_lots`.
- Orders are MARKET/MIS; SELL to open/scale, BUY to cover. Traded options stay subscribed
  until `on_shutdown` (avoids a fill race where unsubscribing kills the cover fill).
- All order calls are wrapped to swallow `RiskCapBreached` etc. without crashing the task.

Paper fills work because `PaperBroker` auto-subscribes `tick.<sid>` once an order exists and
the option is on the live feed.

## Paper journal (`pdp/journal/`)

`stats.py` `compute_daily_stats(trades)` is pure: total premium sold/bought, net premium,
charges, realized P&L (= net premium − charges; valid as everything is flat by EOD),
round-trips, wins/losses, win-rate. `service.py` `JournalService` registers a sync
`record_fill` on `OrdersHub` fill callbacks, buffers per IST-day in memory, and flushes
upserts to MongoDB `paper_journal` via a periodic loop. `routes.py` exposes
`GET /api/v1/journal` and `GET /api/v1/journal/stats`.

## Out of scope (follow-ups)

- Seeding the live SuperTrend from MongoDB history on startup (currently needs `period` fresh
  bars after start).
- Host-level (vs in-strategy) scheduling.
- "Add only while in profit" scale-in variant (param stubbed, default off).
