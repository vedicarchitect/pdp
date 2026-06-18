## Context

On 2026-06-12 the `supertrend_short` strategy produced -₹1,176 in paper trading while the
backtest simulation of the same strategy, same day, same parameters produced +₹25,058. Code
review of `src/pdp/strategies/supertrend_short.py`, `src/pdp/indicators/engine.py`,
`src/pdp/orders/paper.py`, and `backtest_multiday.py` identified five independent bugs that
compound to produce this gap. None require DB schema changes. All are deployable by restarting
the strategy host.

## Goals / Non-Goals

**Goals:**
- Close the five live-vs-backtest execution gaps (see proposal for the full list)
- All fixes deployable without a DB migration or downtime
- No change to the public REST API surface or the paper journal schema

**Non-Goals:**
- Modelling real-world slippage (paper fills will still differ from live broker fills by design)
- Reducing fill latency below 1 tick (1 Redis pub/sub cycle) — that is acceptable
- Multi-strategy indicator sharing (warmup is per-strategy-host startup only)

## Decisions

### D1 — Warmup via `warm_up_indicator_engine()` + `IndicatorEngine.seed_from_bars()`

**Chosen**: Split warmup into an I/O orchestrator and a pure feeder. `pdp.indicators.warmup.
warm_up_indicator_engine(engine, mongo_db, settings, watchlist)` (called once at strategy host
startup, before the market feed starts) loads the last bars from `market_bars` (MongoDB), tops up
from the Dhan intraday API when fewer than `MIN_BARS` rows exist, and hands an ascending-by-`ts`
list to `IndicatorEngine.seed_from_bars()`, which feeds them through `on_bar()`.

**Implementation note (2026-06-13)**: an earlier draft of this decision put a `seed_from_mongo()`
method directly on `IndicatorEngine`. That was rejected during implementation for the same reason
the strategy-layer alternative below was rejected — it couples MongoDB/Dhan access into the engine.
Keeping the engine DB-agnostic (`seed_from_bars` takes plain `BarClosed` objects) and isolating the
data access in `warmup.py` is the more coherent split.

**Alternative considered**: Load prior-day bars in `SuperTrendShort.on_init()` directly. Rejected
because it couples market-data access to the strategy layer, which should stay DB-agnostic.

**lookback / MIN_BARS default**: 10 (well above the period=3 minimum; gives 50 min of history at 5m).

### D2 — Flip atomicity via `get_net_qty` guard before new-leg SELL

**Chosen**: In `_close_current()`, after placing the BUY order, keep `_current = None` (current
behaviour). In `on_bar()`, between `_close_current("flip")` and the subsequent `_open()`, call
`ctx.orders.get_net_qty(old_sid)` and only proceed with `_open()` if `net_qty == 0`. If net_qty
is still non-zero (fill hasn't landed yet), skip the open; the next bar's signal will retry.

**Alternative considered**: await a fill-confirmation event / poll until filled. Rejected because it
blocks the strategy task for an unknown duration and introduces complexity. A one-bar delay on
flip open is an acceptable trade-off — the fill lands within the next Redis tick cycle (~1ms).

**Why the current skip-if-not-flat approach is safe**: MARKET orders on the paper engine fill on
the very next tick (no queue depth). In practice net_qty will almost always be 0 by the time
`get_net_qty` is called. The guard only protects the rare case where the event loop hasn't cycled.

### D3 — Lots sync: derive from positions table at start of each bar

**Chosen**: At the top of `on_bar()`, if `_current` is set, refresh `_current["lots"]` from
`abs(net_qty) // lot_size` using `get_net_qty`. This means the in-memory counter and the DB
are reconciled every bar, making the scale-in cap resistant to restarts and partial fills.

**Alternative considered**: Reconcile only on recovery (in `on_init`). Rejected because a
mid-session crash-restart may recover `_current` but with a stale lots count if any orders
between the last checkpoint and the crash were only partially filled.

### D4 — Paper broker subscription race: pre-warm via `notify_subscribe()`

**Chosen**: Add `PaperBroker.notify_subscribe(security_id)` — a synchronous method that
pre-registers the `security_id` in `_open_orders` with an empty list (so the broker's run-loop
immediately subscribes to `tick.{sid}` on its next iteration, which runs concurrently with the
strategy's `place_order` call). Called from `MarketControl.subscribe()` when broker is paper.
No await needed — the run-loop cycles in <1ms.

**Alternative considered**: Subscribe the Redis channel inside `add_order()` (when the order
arrives). Rejected because `add_order()` is async and the run-loop task would need to coordinate
with an external subscriber coroutine.

**Note**: The race window is already very small (sub-millisecond). This fix eliminates it
structurally rather than relying on timing.

### D5 — LTP staleness: mark only on a fresh option LTP, else skip

**Chosen**: In `_leg_stop_hit()`, read the open option's Redis LTP age by storing
`ltp_ts:{security_id}` alongside `ltp:{security_id}` in Redis (written by the tick router on
each tick). Mark the leg against that LTP only when it is present, positive, and fresher than a
configurable threshold (default 30 seconds). When the LTP is missing or stale, **skip** the stop
on that bar and log `leg_stop_ltp_stale_fallback`; the next bar with a fresh tick catches the move.

**Design correction (2026-06-13)**: an earlier draft of this section said "fall back to
`bar.close` passed down from `on_bar()`". That is wrong for this strategy: `on_bar` is driven by
the NIFTY **index** bar (`bar.security_id == self.sid == "13"`), so `bar.close` is the spot level
(~22,500), not the option premium (~100). Substituting it marks the option against the index and
trips the stop spuriously on every stale-LTP bar. The backtest marks the leg against the
**option's own** bar close (`pos_bars`), which has no synchronous analog inside live `on_bar`;
the only valid live mark is the option's own LTP, so the correct behavior on staleness is to skip,
not to substitute the index close.

**Alternative considered**: when stale, read the option's latest 1m bar close from Mongo
(`option_bars`/`market_bars`) as the mark — the true live analog of the backtest's `pos_bars`.
Rejected for now: it adds a DB read inside `on_bar` and the skip-then-retry behavior already
catches the move within one bar once ticks resume. Revisit if stale gaps prove material in
production.

**LTP timestamp storage**: The tick router already writes `ltp:{sid}` to Redis. Add
`ltp_ts:{sid}` (Unix epoch float, SET with same expiry) in the same write path.

## Risks / Trade-offs

- **D2 one-bar flip delay**: In a fast-moving market, the new leg opens one bar later than
  intended. This is a small but real execution gap. Mitigation: MARKET paper fills land in <1ms;
  the guard will almost never trigger in normal operation.

- **D1 warmup adds startup latency**: Loading 10 bars from MongoDB at startup is ~5ms — negligible.
  If MongoDB is unavailable at startup, log a warning and proceed cold (existing behaviour).

- **D5 ltp_ts write adds one Redis SETEX per tick**: At ~12 ticks/second per security this is
  trivial. The key expires with the same TTL as the LTP key.

## Migration Plan

1. Deploy updated code (no DB migration needed).
2. Restart the strategy host — `on_init` triggers warmup from MongoDB on startup.
3. Verify via `pdp strategy heartbeat` that `st_direction` is non-None from the first bar.
4. Rollback: revert the deploy; no data is changed.

## Open Questions

- Should `lookback_bars` be per-strategy YAML param or a global IndicatorEngine setting?
  Current decision: global default (10), overridable by `on_init` caller — keeps YAML clean.
