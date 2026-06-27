# strategies/ — Concrete Strategy Implementations

Python implementations of trading strategies. Each file implements a class that extends `pdp.strategy.base.BaseStrategy`.

## Files

| File | Purpose |
|------|---------|
| `supertrend_short.py` | `SuperTrendShort` — ST(10,2)/15m NIFTY OTM-1 option-selling |
| `directional_strangle.py` | `DirectionalStrangle` — bias-driven multi-leg ratio strangle; reuses `pdp.signals.bias.score_bias()`; hedge via Rs 2–5 premium-band scan; momentum disabled by default |

## Wiring

Strategies are **not** auto-discovered from this package. They are loaded by `StrategyHost` via YAML config files in `strategies/*.yaml` (root level):

```yaml
# strategies/supertrend_short.yaml
class: pdp.strategies.supertrend_short.SuperTrendShort
```

`StrategyHost` imports the class from the dotted path in `class:`, instantiates it, and calls `on_bar()` for every relevant tick.

## Adding a strategy

1. Create `src/pdp/strategies/my_strategy.py` extending `BaseStrategy`
2. Create `strategies/my_strategy.yaml` (root YAML configs folder) with `class: pdp.strategies.my_strategy.MyStrategy`
3. Restart API — `StrategyHost` auto-loads all `*.yaml`

## Key constraint

All indicator state (SuperTrend values, ATR, etc.) comes from `IndicatorEngine` — strategies do **not** recompute indicators.
