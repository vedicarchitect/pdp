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

## Leg tracking invariants (`directional_strangle.py`)

- **One leg per security.** Open legs live in `self._legs: dict[security_id, OpenLeg]`; `_add_leg`
  raises on a duplicate `security_id` rather than allowing two `OpenLeg`s to track the same broker
  position. `_short_legs`/`_hedge_legs`/`_momentum_legs` are read-only properties derived from
  `_legs`, kept for call-site compatibility — always write through `_add_leg`/`_remove_leg`, never
  append to those properties directly.
- **Lock discipline.** Both the open path and the close path acquire `_lock_for(sid)` around the
  broker `get_net_qty` → `_place` sequence (`_close_leg`, `_partial_close`, `_open_short`/`_open_hedge`/
  `_open_momentum`). `asyncio.Lock` is not re-entrant: `_roll_leg` releases the `_rolling` claim
  *before* calling `_close_leg`/`_open_short` so the close and reopen each acquire the sid lock fresh
  rather than nesting.
- **Divergence is surfaced, not silently corrected.** When in-memory `leg.lots` and broker `net_qty`
  disagree, `LEG_STATE_DIVERGED` is emitted and only the smaller of the two is closed — the code never
  closes more than the broker actually holds. A `close_lots == 0` residual (broker holds a sub-lot
  amount) flags divergence and leaves the leg tracked rather than marking it closed.
- **Leg type is durable, not inferred.** `leg_kind` (`short`/`hedge`/`momentum`) is written to the
  `strategy_leg` table on open and read back on `_rehydrate_legs` — a broker `net_qty` sign alone
  cannot distinguish a long hedge from a long momentum leg. An orphan `Position` with no matching
  `strategy_leg` row is adopted by sign inference as a best effort and flagged `LEG_TYPE_UNKNOWN`.
