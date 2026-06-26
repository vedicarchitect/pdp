# backtest/ — Runnable Backtest Scripts & Configs

Top-level folder for all backtest tooling. Not a Python package — these are runnable scripts
and version-controlled config files. The Python package lives in `src/pdp/backtest/`.

## Files

| Path | Role |
|------|------|
| `run.py` | Single entry point: single-config per-trade detail OR grid sweep |
| `compare.py` | Replay one day, compare vs paper journal (side-by-side, no DB writes) |
| `strangle_run.py` | **Directional-strangle** multi-year runner — quarter-chunked load, replays per day; `--hedge/--no-hedge`, `--trace`, `--out-dir` archives per-day logs |
| `strangle_walkforward.py` | Walk-forward IS/OOS optimizer (go/no-go gate) — grouped-knob grid, stitched OOS equity + verdict |
| `configs/st10_15m_otm1.yaml` | **Default / promoted config** — ST(10,2)/15m/OTM1 |
| `configs/st3_1_5m_otm1.yaml` | Legacy anchor baseline — ST(3,1)/5m/OTM1 (regression anchor) |
| `configs/strangle_premium*.yaml` | Directional-strangle, premium-strike (naked + `_hedged` 2–5₹ wing) |
| `configs/strangle_delta*.yaml` | Directional-strangle, delta-strike (naked + `_hedged`) |

## Directional strangle (bias-driven option selling)

Codifies `strategies/MultiTimeFrameSelling.txt`: a multi-timeframe weighted bias score →
7 buckets → PE:CE sell-lot ratio, India-VIX gate, optional protective hedges. Shared bias
engine in `src/pdp/signals/bias.py` (used by both backtest and the future live strategy).

```bash
task backtest:strangle -- --from 2026-05-01 --to 2026-06-23            # naked
task backtest:strangle -- --config-file backtest/configs/strangle_premium_hedged.yaml
task backtest:strangle -- --from 2026-05-01 --to 2026-06-23 --hedge    # force hedges on
task backtest:strangle -- --start 2026-06-20 --days 3 --trace          # every-minute status
```

Data prerequisites (Mongo): index spot (NIFTY sid 13) + options (`option_bars`) + India VIX
(`task backfill:vix`, sid 21 — intraday history begins ~Aug-2021). Run `task audit:strangle`
to confirm per-year coverage before a multi-year walk.

### Archived runs (`--out-dir`, git-ignored under `backtest/runs/`)

`--out-dir backtest/runs` lays every run down as a self-describing, auditable folder:

```
backtest/runs/<run_id>/            # run_id = strangle_YYYYMMDD-HHMMSS
  manifest.json    config + window + metrics + timing totals + git sha
  summary.csv      one row/day: P&L, trades, drawdown, build_ms, sim_ms
  equity.csv       cumulative realized equity + peak + drawdown by day
  run.log          high-level run log
  days/<YYYY-MM-DD>/
    status.log     every-minute BarStatus trace (score, votes, VIX/PCR, legs, P&L, action)
    trades.csv     every fill: time, side, type, strike, qty, price, leg/day P&L, commission
    legs.csv       closed-leg records (entry/exit/lots/pnl/reason; incl. hedges)
    day.json       that day's summary + per-day build/sim timing
```

Keep these out of git (they're reproducible). For long-term keeping, retain `manifest.json` +
`summary.csv` + `equity.csv` per run (tiny) and prune the per-day `days/` tree once verified.

### Walk-forward (the go/no-go gate)

```bash
task backtest:strangle:wf -- --from 2021-09-01 --to 2026-06-23 --out logs/wf.csv
```

Rolls a fixed IS window forward, selects grouped params on IS only, scores the next unseen OOS
slice; stitches all OOS slices into one honest equity curve and prints a PASS/REVIEW verdict.
Only promote to the Phase-5 paper strategy if OOS is robustly profitable.

## How to run

```bash
# Per-trade detail for the default config, last 7 days (BACKTEST_DEFAULT_CONFIG)
task backtest

# Named config
task backtest -- --config-file backtest/configs/st3_1_5m_otm1.yaml --days 30

# Inline JSON config
task backtest -- --config '{"st_period":10,"st_multiplier":2,"timeframe_min":15,"moneyness":1}'

# Grid sweep — pass at least one grid flag (--st / --tf / --moneyness) to trigger grid mode
task backtest:sweep -- --days 90 --st "3,1;10,2" --tf "5,15" --moneyness "1,0,-1"

# Paper journal comparison for a date
task backtest:compare -- --date 2026-06-12
```

## Config YAML shape

Each `configs/*.yaml` is a flat serialization of `StrategyConfig.to_dict()` — exact same keys,
no nested sections. Load with `StrategyConfig.from_yaml("backtest/configs/my.yaml")`.

```yaml
st_period: 10
st_multiplier: 2.0
timeframe_min: 15       # supported: 3, 5, 15, 30, 60
moneyness: 1            # +N = OTM, 0 = ATM, -N = ITM
strike_step: 50
base_lots: 2
add_lots: 1
max_lots: 5
lot_size: 65
start_ist: "09:30"
squareoff_ist: "15:10"
leg_stop_per_lot: 3000.0
day_stop: 20000.0
roll_enabled: true
roll_trigger_prem: 20.0
roll_target_min_prem: 50.0
scale_in_gate: premium_break
flip_mode: strangle
```

## How to add a new config

1. Copy an existing YAML: `cp backtest/configs/st10_15m_otm1.yaml backtest/configs/my_new.yaml`
2. Edit the fields. `timeframe_min` must be one of: 3, 5, 15, 30, 60.
3. Run `task backtest -- --config-file backtest/configs/my_new.yaml --days 7` to verify.
4. Commit the YAML — configs are the "what we ran" record.

## Frontend seam

The YAML shape mirrors the future `POST /api/v1/backtest/run` request body exactly.
`StrategyConfig.from_yaml(path)` and `from_dict(data)` share the same validation path,
so a YAML file and an API payload are interchangeable — no API changes in this change.

## Default config

`BACKTEST_DEFAULT_CONFIG` env var (default `"backtest/configs/st10_15m_otm1.yaml"`) controls
which config `task backtest` uses when no `--config-file` or `--config` flag is given.
Override in `.env` to switch the default without changing code.
