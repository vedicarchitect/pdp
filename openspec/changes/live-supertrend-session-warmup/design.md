## Context

`warm_up_indicator_engine(engine, mongo_db, settings, watchlist)` (`src/pdp/indicators/warmup.py`)
runs once at startup (`src/pdp/main.py:125`). For each watchlist `(security_id, segment, timeframe)`
it calls `_warm_one`, which reads `market_bars` for `ts >= now - LOOKBACK_HOURS` (8h), and if fewer
than `MIN_BARS` (10) rows exist *and* Dhan creds are set, fetches more from Dhan, persists, merges,
then `engine.seed_from_bars(bars)`. The `IndicatorEngine` tracker is created once per
`(security_id, timeframe)` and never reset, so once seeded it stays continuous across day
boundaries — the issue is purely the **seed window on a fresh (restart) tracker**.

NIFTY session: 09:15–15:30 IST (03:45–10:00 UTC). Overnight gap to next open ≈ 17.75h; weekend/long
holiday gaps are larger still. An 8h wall-clock lookback from any intraday moment cannot reach the
prior session.

## Goals

- On any restart time, seed the tracker with the **most recent prior trading session** so the
  carried-over SuperTrend direction is established before the first live bar (parity with Kite and
  with the backtest's `_prior_session_5m`).
- Keep a continuously-running process unaffected (no tracker reset, no behavior change).

## Decisions

### Session-aware lookback (replaces fixed 8h)
- Compute the **most recent prior trading day** by walking back from "today" over weekends and NSE
  holidays (reuse `pdp.options.gap_backfill.trading_days` / `holidays`, already used by the spot/
  options backfills), then set the Mongo `since` to that prior day's session start (≈03:45 UTC).
- This guarantees the window `[since, now]` spans the full prior session plus today, regardless of
  restart time — so the seed always carries the prior direction.
- Edge: if the prior trading day has no `market_bars` (data gap), fall through to the Dhan fallback
  (below) to fetch it, rather than silently cold-starting.

### Warmup target sized to a full prior session
- Raise the "is Mongo sufficient?" bar from `MIN_BARS = 10` to a session-sized target (e.g. enough
  bars to cover the prior session at the tracked timeframe) so a thin Mongo triggers the Dhan
  fallback to fetch the **prior session**, not just 10 same-day bars.
- The Dhan fetch range must likewise extend to the prior session start (the current `_fetch_from_dhan`
  hardcodes yesterday/today — acceptable for a single prior session, but verify it covers the
  walked-back prior trading day across weekends/holidays; widen its `from_date` to the computed prior
  session if needed).

### No IndicatorEngine change
- `IndicatorEngine` already persists trackers across days; do not add a reset. The fix is isolated to
  `warmup.py` seeding.

## Risks / trade-offs

- **Larger startup fetch:** seeding a full prior session is more bars than 10, but it is one-time at
  startup and bounded (~one session per watchlist entry); within the latency budget (warmup is not on
  the tick hot path).
- **Holiday-cluster correctness:** walking back via the holiday calendar (not a fixed hour count) is
  what makes long weekends / holiday clusters correct — the reason a fixed 72h window was rejected.
- **Data-gap days:** if the prior session is missing locally, the Dhan fallback covers it; if Dhan is
  also unavailable, the tracker cold-starts as today (documented fallback, no worse than current).

## Verification

- Unit: with a synthetic Mongo across a weekend gap, `since` resolves to the prior *trading* session,
  and the seed yields the carried-over direction (not a cold-start DOWN seed) for a mid-day restart.
- Manual/integration: start the paper process mid-session; `indicator_warmup_done` logs a direction
  matching the prior-session close trend (and the chart), not a fresh DOWN seed.
