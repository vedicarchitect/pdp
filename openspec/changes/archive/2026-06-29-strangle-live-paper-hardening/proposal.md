## Why

The 2026-06-29 three-index directional-strangle paper session (`/strangle-review`) exposed five
defects — two are correctness/safety bugs that corrupted the run, three degrade signal quality:

1. **Option LTP never reached the strategy.** Every leg logged `ltp: null` / `mtm: null` all day.
   `StrategyHost.on_tick()` filters ticks through a **static** YAML watchlist (index SID only), so
   option legs subscribed at runtime via `ctx.market.subscribe()` are dropped before
   `strategy.on_tick()` runs and `_ltp_cache` stays empty. MTM, premium-stops, and rollups were
   blind the whole session. (The paper broker still filled because it listens on Redis pub/sub.)
2. **Paper P&L fabricated a loss → BANKNIFTY `day_loss_cap` at −₹59,046.** When `_await_fill_avg_px`
   times out (far-OTM hedges tick late), a leg is recorded with `avg_price = 0`. `upsert_position`
   has no zero-average guard, so closing that short computes `realized = (0 − close_px)·qty` — a
   large fake loss. Stacked across bucket churn, it breached the day limit on phantom money.
3. **Bias engine ran on one signal.** Only `ema_5m` ever voted; `ema_1h`, `ema_15m`, `cam_weekly`,
   `vwap`, `pcr` were all absent (warmup gap, missing `1w` timeframe, zero-volume index VWAP,
   hardcoded `None` PCR). A single 5m EMA flip churned buckets — 3 reversals in 15 min on BANKNIFTY.
4. **No bucket hysteresis.** Any bucket change triggers an immediate close/reopen, so the chatter in
   (3) caused rapid open→close cycles that compounded (2).
5. **A triggered `day_loss_cap` does not survive a restart.** `_done_for_day` resets on startup, so a
   same-day restart silently re-enters after the kill.

## What Changes

- **Route live option LTP to the owning strategy** — the host keeps a per-running-strategy dynamic
  subscription set; `MarketControl.subscribe()`/`unsubscribe()` register/clear SIDs with the host;
  tick dispatch matches the static watchlist **∪** the dynamic set. Legs are cleared on close/stop.
- **Paper fill integrity (no zero-price fills, no fabricated losses)** — paper MARKET fills use the
  best available price (cached Redis `ltp:<sid>`) at placement and never persist `avg_price = 0`;
  `upsert_position` refuses to compute realized P&L against a zero stored average (skip + warn).
  Hedge opens record the day-baseline like shorts/momentum.
- **Full bias signal set** — wire `pcr` from the option-chain poller, add `1w` weekly-Camarilla
  support, fix `ema_1h`/`ema_15m` warmup seeding, and compute `vwap` from index **futures** volume
  (the index spot has none). This dilutes `ema_5m` from ~⅓ of the score toward ~⅛.
- **Bucket-change hysteresis** — a new bucket must persist `bucket_confirm_bars` (default 2)
  consecutive bars before the strategy closes/reopens; reverts reset the counter.
- **Persist the day-loss halt** — a per-strategy, per-IST-day halt marker survives restart and
  blocks re-entry until the next trading day; it clears on IST date rollover.

## Capabilities

### Modified Capabilities
- `strategy-host`: tick dispatch also delivers ticks for SIDs subscribed at runtime, not only the
  static watchlist.
- `paper-pnl-correctness`: MARKET fills never record a zero average price; realized P&L is never
  computed against a zero stored average.
- `directional-strangle`: full bias signal set, bucket-change hysteresis, hedge day-baseline, and a
  restart-durable day-loss halt.

## Impact

- **`backend/pdp/strategy/host.py`**: per-strategy dynamic SID set + dispatch over static ∪ dynamic.
- **`backend/pdp/strategy/context.py`**: `subscribe`/`unsubscribe` notify the host.
- **`backend/pdp/orders/paper.py`**: best-price MARKET fill (cached LTP); zero-average guard in
  `upsert_position`.
- **`backend/pdp/strategies/directional_strangle.py`**: clear dynamic subs on close; `_open_hedge`
  day-baseline; bias-input wiring (`_build_bias_inputs`); `bucket_confirm_bars` debounce at the
  bucket-change site; restart-durable halt marker (load on start, set on cap, clear on day rollover).
- **`backend/pdp/signals/bias.py`**: VWAP-from-futures handling; ensure all configured votes are
  emitted when inputs are present.
- **`backend/pdp/options/`**: expose a PCR reading from the chain poller.
- **`backend/pdp/indicators/warmup.py`**: seed 15m/1h EMA and the new `1w` pivots before first bar.
- **`backend/strategies/directional_strangle_*.yaml`**: add `1w` timeframe; `bucket_confirm_bars`.
- **`backend/pdp/settings.py`**: `BUCKET_CONFIRM_BARS` default (if not per-strategy only).
- **`docs/RUNBOOK.md`**: operating notes for the LTP path, halt persistence, and signal wiring.

**Depends on:** none (sits on top of the merged `ops-safety-net` stack). Paper-only; `LIVE=0`.
