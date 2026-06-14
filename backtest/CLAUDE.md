# backtest/

Top-level folder for all backtest tooling. Not a Python package — these are runnable scripts
and version-controlled config files.

## Files

| Path | Role |
|------|------|
| `run.py` | Single entry point: grid sweep OR single-config per-trade detail |
| `compare.py` | Replay one day, compare vs paper journal (side-by-side) |
| `configs/` | Named YAML strategy configs (one file per config) |

> **Note:** `run.py` and `compare.py` will be created when OpenSpec change `backtest-consolidate` is implemented. Skeletons are in `scripts/backtest_sweep.py` and `scripts/backtest_compare.py` until then.

## Config YAML shape

Each `configs/*.yaml` is a flat serialization of `StrategyConfig.to_dict()`:

```yaml
id: my_config_name
name: "Human-readable label"
st_period: 10
st_multiplier: 2.0
timeframe_min: 15       # minutes; supported: 3, 5, 15, 30, 60
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
scale_in_gate: "premium_break"
flip_mode: "strangle"
```

Load with `StrategyConfig.from_yaml("backtest/configs/my_config.yaml")`.

## How to run

```bash
# Per-trade detail for the default config, last 7 days
task backtest

# Per-trade detail for a named config
task backtest -- --config-file backtest/configs/st3_1_5m_otm1.yaml --days 30

# Full grid sweep
task backtest:sweep -- --days 90 --st "3,1;10,2" --tf "5,15" --moneyness "1,0,-1"

# Compare one day vs paper journal
task backtest:compare -- --date 2026-06-12
```

## Adding a new config

1. Copy an existing YAML: `cp backtest/configs/st10_15m_otm1.yaml backtest/configs/my_new.yaml`
2. Edit the fields. `timeframe_min` must be one of: 3, 5, 15, 30, 60.
3. Run `task backtest -- --config-file backtest/configs/my_new.yaml --days 7` to verify.
4. Commit the YAML.

## Frontend seam

The YAML shape is intentionally identical to the future `POST /api/v1/backtest/run` request body.
When the API endpoint is built, the frontend will POST this dict and the backend will call
`StrategyConfig.from_dict(body)` — the same path as `from_yaml`.

## Key constraint

`BACKTEST_DEFAULT_CONFIG` env var (default `"backtest/configs/st10_15m_otm1.yaml"`) controls
which config `task backtest` uses. Override in `.env` to switch default without changing code.
