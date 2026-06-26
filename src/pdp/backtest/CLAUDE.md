# Backtest Module (`src/pdp/backtest/`)

Python package — importable modules only. Runnable scripts and YAML configs live in `backtest/` (repo root).

## Active files

| File | Role |
|------|------|
| `sim.py` | **Active index simulation engine** — config-driven tick-by-tick replay, fill logic, P&L tracking |
| `strangle_sim.py` | **Directional-strangle engine** — bias-driven multi-leg ratio strangle (PE:CE per bucket), protective hedges, rollup/take-profit/premium-doubled/trend-flip exits, every-minute `BarStatus` trace |
| `strangle_config.py` | `StrangleConfig` dataclass — bias weights, ratio table, strike method, hedge band, exits; `from_yaml`/`to_yaml` |
| `strangle_loader.py` | Assembles per-bar multi-timeframe `BiasInputs` (5m/15m/1h EMAs, daily+weekly Camarilla, swing, VWAP, ORB, India VIX) from a cached Mongo window for `strangle_sim.py` |
| `strangle_report.py` | `RunWriter` — archives per-day artifacts (status.log, trades.csv, legs.csv, day.json) + run-level summary.csv/equity.csv/manifest.json with build/sim timing |
| `day_loader.py` | Loads one trading day of index spot + option bars from MongoDB for `sim.py` |
| `strategy_config.py` | `StrategyConfig` dataclass — all strategy knobs; `from_dict` / `to_dict` / `from_yaml` / `to_yaml` |
| `commissions.py` | `CommissionCalculator` — uses `settings.backtest_commission.*` |
| `execution.py` | Fill execution (no look-ahead: fills on next bar open after signal) |
| `resample.py` | OHLCV resampling (1m → 5m/15m etc.) |
| `chain_loader.py` | Loads option chain snapshots for a day |
| `indicators.py` | Backtest-time indicator compute (replays bars to rebuild ST state) |
| `models.py` | `BacktestResult`, `Trade`, `DayResult` dataclasses |
| `engine.py` | Generic strategy-replay framework (`BacktestEngine`) — not used by the index sim directly |
| `output.py` | Result formatting, console table, CSV/JSON export |
| `routes.py` | `/backtest` FastAPI endpoints |

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

## Key Constraints

- **No look-ahead**: signals on bar close → fill on **next bar open**. Enforced in `execution.py`.
- **No live indicator recompute**: backtest rebuilds ST bar-by-bar via `indicators.py`, mirrors live `IndicatorEngine` params.
- Data source: MongoDB `option_bars` and `market_bars` collections.
- `strategy_config.py` is the canonical config format; YAML files in `backtest/configs/` are its serialized form.
- **Suite indicators in backtest**: set `suite_indicators` in `StrategyConfig` to replay any live-suite family alongside ST. `sim.py` builds the bundle, warms it from `prior_session_bars`, and updates it per bar — same tracker classes as live, so states are identical. The snapshot lands as `_suite_snap` in the series loop, ready for strategy conditions.

## Common Tasks

**Add a commission field:** Edit `BacktestCommissionSettings` in `settings.py` + update `commissions.py`.

**Change fill timing:** Only touch `execution.py`. Do NOT change `sim.py` fill logic directly — keep look-ahead guard in one place.

**Add a new StrategyConfig knob:** Edit `StrategyConfig` in `strategy_config.py`, update `sim.py` to consume it, add validation in `validate()`.
