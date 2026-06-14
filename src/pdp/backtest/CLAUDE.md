# Backtest Module

## Files

| File | Size | Role |
|------|------|------|
| `sim.py` | 20 KB | Core simulation loop — tick-by-tick replay, fill logic, P&L tracking |
| `engine.py` | 10 KB | `BacktestEngine` — orchestrates day loading, sim runs, result aggregation |
| `commissions.py` | 2.4 KB | `calc_commission(value, qty, settings)` — uses `settings.backtest_commission.*` |
| `execution.py` | 3 KB | Fill execution (no look-ahead: fills on next bar open after signal) |
| `day_loader.py` | 6 KB | Loads one trading day of option bars from MongoDB |
| `chain_loader.py` | 4 KB | Loads option chain snapshots for a day |
| `indicators.py` | 6 KB | Backtest-time indicator compute (replays bars to rebuild ST state) |
| `resample.py` | 5 KB | OHLCV resampling (1m → 5m/15m etc.) |
| `strategy_config.py` | 6.5 KB | Parses strategy YAML into `StrategyConfig` |
| `models.py` | 2.9 KB | `BacktestResult`, `Trade`, `DayResult` dataclasses |
| `output.py` | 7.8 KB | Result formatting, console table, CSV/JSON export |
| `routes.py` | 4.9 KB | `/backtest` FastAPI endpoints |

## Commission Settings (settings.py → `backtest_commission`)

| Field | Default |
|-------|---------|
| `brokerage_per_order` | ₹20.00 |
| `stt_rate` | 0.001 (0.1%) |
| `txn_charge_rate` | 0.0003553 |
| `sebi_rate` | 0.00001 |
| `stamp_duty_rate` | 0.00004 |
| `gst_rate` | 0.18 (18%) |

Override via `.env`: `BACKTEST_COMMISSION__BROKERAGE_PER_ORDER=15`

## Top-Level Backtest Scripts (repo root)

```bash
uv run python backtest_multiday.py   # multi-day sweep (main, 58 KB)
uv run python backtest_full_day.py   # single full day (11 KB)
uv run python backtest_today.py      # today only (9.7 KB)
```

## Key Constraints

- **No look-ahead**: signals on bar close → fill on **next bar open**. Enforced in `execution.py`.
- **No live indicator recompute**: backtest rebuilds ST bar-by-bar via `backtest/indicators.py`, mirrors live `IndicatorEngine` params (period=3, mult=1).
- Data source: MongoDB `option_bars` collection (warehoused via `warehouse/` module from Abi DuckDB).
- Active in-flight specs related to backtest: `backtest-data-integrity-and-flip-gate`, `backtest-fill-timing-no-lookahead`, `live-backtest-parity`, `configurable-strategy-backtest-sweep`.

## Common Tasks

**Add a commission field:** Edit `BacktestCommissionSettings` in `settings.py` + update `commissions.py:calc_commission()`.

**Change fill timing:** Only touch `execution.py`. Do NOT change `sim.py` fill logic directly — keep look-ahead guard in one place.

**Add output column:** Edit `output.py`. `BacktestResult` models are in `models.py`.
