# strategies/ — Strategy YAML Configs (Root Level)

YAML configuration files for strategies. `StrategyHost` auto-loads all `*.yaml` at startup.

> **This folder** (`strategies/`) holds **YAML configs** only.
> Python implementations live in `src/pdp/strategies/`.

## Files

| File | Purpose |
|------|---------|
| `supertrend_short.yaml` | Active: ST(3,1) NIFTY OTM short option-selling |
| `example.yaml.tpl` | Template — copy to add a new strategy |

## Adding a new strategy

```powershell
cp strategies\example.yaml.tpl strategies\my_strategy.yaml
# Edit: set id, class, watchlist, params, risk
# Then implement src/pdp/strategies/my_strategy.py
# Restart API — auto-loaded
```

## Key YAML fields

```yaml
id: supertrend_short                          # unique, matches file stem
class: pdp.strategies.supertrend_short.SuperTrendShort  # importable dotted path
watchlist:
  - security_id: "13"      # Dhan security_id (NIFTY = "13")
    exchange_segment: IDX_I
    timeframes: [5m]
params:
  lot_size: 65
  start_lots: 2
  max_lots: 5
  start_ist: "09:30"
  square_off_ist: "15:10"
  leg_stop_per_lot: 1000
  day_stop: 10000
risk:
  max_open_orders: 12
  max_daily_loss_inr: 20000
```
