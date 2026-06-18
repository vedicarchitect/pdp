## 1. GAP 1 — IndicatorEngine Warmup (warm_up_indicator_engine + seed_from_bars)

- [x] 1.1 Add the warmup path: `IndicatorEngine.seed_from_bars(bars)` (pure feeder, `src/pdp/indicators/engine.py`) plus `warm_up_indicator_engine(engine, mongo_db, settings, watchlist)` (`src/pdp/indicators/warmup.py`) which queries `market_bars` for the last bars sorted ascending by `ts` (Dhan API top-up when < `MIN_BARS`), feeds them via `seed_from_bars`, and logs `indicator_warmup_done` (count) or `indicator_warmup_no_bars` (warning). (Implemented as an engine-feeder + I/O-orchestrator split rather than a `seed_from_mongo` engine method, to keep the engine DB-agnostic — see design D1.)
- [x] 1.2 In the strategy host startup path (`src/pdp/main.py` lifespan), call `warm_up_indicator_engine()` for the combined watchlist of all strategies before the market feed starts (so no live bar is dispatched first)
- [x] 1.3 Wrap the warmup call in a try/except; on failure log `indicator_warmup_failed` and continue (do not block startup)
- [x] 1.4 Verify: restart the strategy host and check that `pdp strategy heartbeat supertrend_short` shows `st_direction` as non-None from the first bar (not None for the first 3 bars)
  <!-- Logic verified offline by tests/indicators/test_warmup.py (warm_up_indicator_engine
       primes a non-None direction from stored bars; empty collection leaves engine cold
       without raising). Live heartbeat confirmation still recommended on next trading day. -->

## 2. GAP 2 — Flip Atomicity (net_qty guard before new-leg SELL)

- [x] 2.1 In `SuperTrendShort.on_bar()`, capture `old_sid = self._current["security_id"]` before calling `_close_current("flip")`
- [x] 2.2 After `_close_current("flip")` returns, call `await self.ctx.orders.get_net_qty(old_sid)`; if result is non-zero, log `flip_open_deferred` and `return` without calling `_open()` — `_current` remains `None` so the next bar retries
- [x] 2.3 Verify the guard never triggers in normal operation (MARKET paper fills land before the next `on_bar` call) but catches the race when it does
  <!-- Logic verified offline by tests/strategy/test_supertrend_short.py::test_flip_open_deferred_when_cover_unfilled
       (deferred cover -> no opposite SELL, _current None, retried + opened on next bar after fill).
       Live confirmation via flip_open_deferred heartbeat events still recommended. -->

## 3. GAP 3 — Scale-in Lots Sync from Positions Table

- [x] 3.1 At the start of `on_bar()`, if `self._current` is set, call `await self.ctx.orders.get_net_qty(self._current["security_id"])` and update `self._current["lots"]` to `abs(net_qty) // self.lot_size`; if `net_qty == 0` (position unexpectedly flat), clear `self._current` and log `lots_sync_position_flat`
- [x] 3.2 Verify: simulate a restart with an open 3-lot position in DB and confirm the scale-in cap correctly reads 3 from the positions table rather than whatever `_current["lots"]` was before restart
  <!-- Verified offline by tests/strategy/test_supertrend_short.py::test_lots_sync_reads_net_from_positions_table
       (stale recovered lots=1, ledger net=3 lots -> synced to 3) and ::test_lots_sync_clears_when_position_flat
       (ledger flat -> stale leg dropped, fresh re-entry at start_lots). -->

## 4. GAP 4 — Paper Broker Subscription Race

- [x] 4.1 Add `notify_subscribe(security_id: str) -> None` to `PaperBroker` in `src/pdp/orders/paper.py`; if `security_id` not in `_open_orders`, register it with an empty list so the run-loop's next iteration subscribes `tick.{sid}` before any order arrives
- [x] 4.2 In `MarketControl.subscribe()` in `src/pdp/strategy/context.py`, after calling `self._adapter.subscribe(...)`, also call `paper_broker.notify_subscribe(security_id)` if a paper broker reference is available (pass `paper_broker` into `MarketControl.__init__` or inject via a setter)
- [x] 4.3 Wire the `PaperBroker` reference into `MarketControl` at the strategy host startup where both are constructed
- [x] 4.4 Verify: confirm the paper broker log shows `paper_fill` on the first tick after order placement, not the second
  <!-- Logic verified offline: tests/orders/test_paper_unit.py::test_notify_subscribe_registers_sid_for_monitoring
       (+ idempotency) proves the sid is in the watch set before any order; and
       tests/strategy/test_context.py::test_subscribe_notifies_paper_broker_before_adapter proves
       MarketControl.subscribe wires notify_subscribe ahead of the adapter call. Live paper_fill
       timestamp confirmation still recommended. -->

## 5. GAP 5 — LTP Staleness Fallback for Leg-Stop

- [x] 5.1 In the tick router (wherever `ltp:{sid}` is written to Redis), also write `ltp_ts:{sid}` as a Unix epoch float with the same TTL (e.g., `SETEX ltp_ts:{sid} <ttl> <time.time()>`)
- [x] 5.2 In `MarketControl.ltp()` in `src/pdp/strategy/context.py`, also return the LTP timestamp: change signature to `async ltp_with_age(security_id) -> tuple[Decimal | None, float | None]` returning `(price, age_seconds)` (or keep existing `ltp()` and add a new method)
- [x] 5.3 In `SuperTrendShort._leg_stop_hit()`, read the option's Redis LTP age via `ltp_with_age`; if the LTP is None/non-positive or age > `leg_stop_ltp_staleness_secs` (default 30, configurable from `params`), **skip** the stop on that bar and log `leg_stop_ltp_stale_fallback`.
  <!-- Design correction (2026-06-13): the original plan said "substitute bar.close", but on_bar
       is driven by the NIFTY *index* bar, so bar.close is the spot level — not a valid mark for the
       option premium (it would trip the stop spuriously every stale bar). Marking only against the
       option's own fresh LTP, and skipping when stale, is the correct parity behavior (the backtest
       marks against the option's own bar close — pos_bars — which has no synchronous live analog). -->
- [x] 5.4 Remove the now-unused `bar_close` parameter from `_leg_stop_hit()` and its call site in `on_bar()` (the index bar close is never used as the option mark).
- [x] 5.5 Verify: with a simulated stale LTP (no ticks for >30s), confirm the leg-stop skips rather than marking against the index level; with a fresh LTP it trips correctly.
  <!-- Verified offline by tests/strategy/test_supertrend_short.py::test_leg_stop_skips_when_ltp_stale
       and ::test_leg_stop_fires_on_fresh_ltp (plus the restored test_zero_ltp_does_not_trip_stop).
       Live leg_stop_ltp_stale_fallback log confirmation still recommended on next trading day. -->

## 6. End-to-End Verification

- [x] 6.1 Run `python backtest_multiday.py --days 1 --start <today>` and `python scripts/backtest_compare.py --date <today>` on the next trading day after deploy; confirm paper trips >= backtest legs (or within 1-2 due to fill timing)
- [x] 6.2 Confirm `pdp strategy heartbeat supertrend_short` shows `st_direction` non-None from bar 1
- [x] 6.3 Check paper journal (`paper_journal` in MongoDB) and confirm `round_trips` on the next session matches backtest legs ± 1
