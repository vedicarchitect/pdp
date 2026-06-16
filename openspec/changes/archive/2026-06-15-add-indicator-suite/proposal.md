## Why

Rule #4 of the project is **"Universal indicators — `IndicatorEngine` computes once;
strategies consume, never recompute."** Today that rule is honoured by exactly **one**
indicator: a single `SuperTrendTracker` per `(security_id, timeframe)` held in
`IndicatorEngine` (`src/pdp/indicators/engine.py`), computed once in the `TickRouter` hot
path (`src/pdp/market/router.py:112`) and read read-only via `ctx.indicators.supertrend(...)`
(`src/pdp/strategy/context.py:28`).

Strategies increasingly need more signals (pivots, EMAs, RSI, VWAP, profiles, FVG), and the
only way to get them today is to recompute inside each strategy — which violates Rule #4,
duplicates work, and drifts live away from backtest. We need **one shared indicator suite**
that computes every supported indicator once and is consumed everywhere (strategies,
backtest, UI). It must absorb **continuous WebSocket feeds for 200+ instruments at once**
(options + futures + stocks + indices) and update **within microseconds per instrument**
inside the existing `tick→WS p99 ≤ 50ms` budget.

This change is **paper-first and additive** — it does not alter SuperTrend's existing
live/backtest behaviour or any strategy's trading logic; it only adds the shared compute
layer that strategies may opt into.

## What Changes

- Introduce an **`indicator-suite`** capability: a single shared compute layer covering
  **EMA (9/20/50/100/200), RSI, Parabolic SAR, VWAP, VWMA, standard pivots, Camarilla pivots
  (pivot/R3/R4/S3/S4), Fibonacci pivots, FVG (fair-value gaps), Market Profile, and Volume
  Profile (POC/VAH/VAL)** — alongside the existing **SuperTrend**.
- Each indicator family is a stateful **`*Tracker`** with an **O(1) `update()`** on
  **`float64`** state (`__slots__`, no per-bar reallocation) and a frozen **`*State`** result.
  SuperTrend stays on `Decimal` and is **unchanged** to preserve validated live↔backtest parity.
- Rework **`IndicatorEngine`** from a single-SuperTrend map into a per-`(security_id,
  timeframe)` **bundle** of trackers, driven by config. A **registry** (`registry.py`) maps
  family name → tracker factory + default params so only requested families are built.
- **Config-driven selection**: each watchlist entry declares an optional `indicators: [...]`
  list (with per-family params). The engine computes only the **union** of what strategies
  request per `(instrument, timeframe)`. Heavy histograms (Market/Volume Profile) are opt-in,
  so 200+ instruments stay within budget.
- Extend **`IndicatorReader`** (`strategy/context.py`) with read-only accessors per family
  plus a `snapshot(sid, tf)` bundle. `ctx.indicators.supertrend(...)` keeps working unchanged.
- Publish the snapshot to **Redis** in `TickRouter` (e.g. `ind:{sid}:{tf}`) for the WS hub/UI,
  mirroring the existing SuperTrend publish; no blocking on the hot path.
- Extend **warmup** to prime every configured family from the prior session (pivots from
  prior-session HLC); failures stay non-fatal.
- **Backtest** reuses the same tracker classes so suite indicators match live exactly.

## Capabilities

### New Capabilities

- `indicator-suite`: the shared, config-driven, float64 O(1) compute layer for all indicators
  (EMA, RSI, Parabolic SAR, VWAP, VWMA, standard/Camarilla/Fibonacci pivots, FVG, Market
  Profile, Volume Profile) consumed read-only by strategies, backtest, and UI.

### Modified Capabilities

- `strategy-config`: watchlist entries gain an optional `indicators` list (with per-family
  params) selecting which suite indicators to compute per `(instrument, timeframe)`.

## Impact

- Depends on `market-data` (`BarClosed` on the `TickRouter` hot path), `strategy-host`
  (`IndicatorReader` / `StrategyContext`), `strategy-config` (watchlist schema), and `backtest`
  (tracker reuse for parity). Reuses existing session-aware warmup (`indicators/warmup.py`).
- Modified: `src/pdp/indicators/engine.py`, `__init__.py`, `warmup.py`, `CLAUDE.md`;
  `src/pdp/strategy/context.py`, `src/pdp/strategy/registry.py` (+ watchlist schema);
  `src/pdp/main.py`, `src/pdp/market/router.py`, `src/pdp/settings.py`, `src/pdp/backtest/sim.py`.
- Added: `src/pdp/indicators/{registry.py, snapshot.py, ema.py, rsi.py, psar.py, vwap.py,
  vwma.py, pivots.py, fvg.py, market_profile.py, volume_profile.py}` and matching tests under
  `tests/indicators/`.
- Paper-first: compute-only; no order-path or live behaviour change. SuperTrend untouched.
- Tests: per-family unit tests against known fixtures, config-driven selection test,
  live↔backtest parity test, and a 200+-instrument latency micro-benchmark.
