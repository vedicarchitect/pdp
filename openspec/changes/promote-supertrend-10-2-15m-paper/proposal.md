# Promote SuperTrend(10,2) / 15m to the paper strategy

## Why

The live/paper `supertrend_short` strategy ran SuperTrend(3,1) on the 5-minute timeframe, which the
2026-06-14 parameter sweep (`scripts/backtest_sweep.py`, 83 trading days) showed to be a structural
loser: **PF 0.48, net −291,641**. The same sweep found the SuperTrend period/multiplier and the
signal timeframe — not the entry/exit micro-rules — drive the edge. Under the *existing* live
semantics (simple flip, scale-every-bar), **ST(10,2) on 15m with per-leg/day stops of 3,000/20,000
returns PF 4.12, net +277,373** over the same window. Promoting these parameters turns the strategy
profitable without any new strategy logic. Scope is paper only.

## What Changes

- Make the universal `IndicatorEngine` SuperTrend parameters settings-driven
  (`SUPERTREND_PERIOD`, `SUPERTREND_MULTIPLIER`), defaulting to **(10, 2)** instead of the
  hardcoded (3, 1) in `main.py`.
- Retune `strategies/supertrend_short.yaml`: signal timeframe **5m → 15m** (watchlist + params),
  per-leg stop **1,000 → 3,000**, day stop **10,000 → 20,000**. Moneyness (OTM-1) and sizing
  (2/1/5) unchanged.
- No change to strategy *logic* (entry, flip-close-reverse, scale-in, stops, square-off all as-is).
  The richer backtest-only semantics (flip→strangle, premium-break scale-in, roll-up) are
  deliberately **not** ported — the sweep showed they did not beat the simple logic at these params.
- Document the strategy flow (`docs/supertrend_short_strategy.md`).

## Impact

- Affected specs: `supertrend-strategy` (promoted default signal configuration).
- Affected code: `src/pdp/settings.py`, `src/pdp/main.py`, `strategies/supertrend_short.yaml`.
- Risk: **paper only** (rule #2 — live requires `LIVE=1`+`BROKER=dhan`+creds, unchanged). The 15m
  timeframe is already supported by the bar aggregator and indicator warmup. Behaviour change is a
  parameter retune; no migrations, no schema changes.
