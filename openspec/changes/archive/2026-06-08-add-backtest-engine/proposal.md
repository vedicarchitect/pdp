## Why

(STUB.) Backtests must run against the same `Strategy` interface as live, using MongoDB `market_bars` history, and produce comparable trade logs / equity curves.

## What Changes

- `pdp backtest run <strategy_id> --from --to` CLI.
- Event-driven loop replays historical bars/ticks into the same `Strategy` hooks used in live.
- Polars-vectorized indicators pre-computed once per (security, timeframe).
- Output: `backtest_runs`, `backtest_trades`, `backtest_daily` tables + CSV in `backtest/results/`.

## Capabilities

### New Capabilities

- `backtest`: Historical replay engine sharing the `Strategy` interface.

### Modified Capabilities

(none)

## Impact

Depends on `market-data`, `strategy-host`.
