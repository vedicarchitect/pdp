# Indicators Module

## Files

| File | Role |
|------|------|
| `engine.py` | `IndicatorEngine` — holds one `SuperTrendState` per `(security_id, timeframe)`. Call `update(bar)` on each closed bar. |
| `supertrend.py` | Pure `SuperTrendState` dataclass + `compute()`. Parameters: `period=3, multiplier=1`. Returns `(direction, upper, lower, value)`. |
| `warmup.py` | `warm_up_indicator_engine()` — seeds engine from MongoDB `market_bars` on startup so ST is valid on first live bar. |
| `__init__.py` | Exports `IndicatorEngine`, `SuperTrendState`. |

## Rules

- **Never** add indicator compute logic inside a strategy class. Always add to `engine.py`.
- New indicators: add a `*State` dataclass here, register in `IndicatorEngine.update()`, expose via `StrategyContext.indicators` (see `strategy/context.py`).
- `IndicatorEngine` is singleton per app — injected via `app.state.indicator_engine`.
- Warmup reads from MongoDB `market_bars` collection (see `mongo/collections.py` for TTL/index info).

## Key types

```python
# engine.py
class IndicatorEngine:
    def update(self, security_id: str, tf: str, bar: Bar) -> IndicatorSnapshot: ...
    def get(self, security_id: str, tf: str) -> IndicatorSnapshot | None: ...

# supertrend.py
@dataclass
class SuperTrendState:
    direction: int   # 1 = bullish, -1 = bearish
    value: Decimal
    upper: Decimal
    lower: Decimal
```

## Common Tasks

**Add a new indicator (e.g. EMA):**
1. Create `ema.py` with `EMAState` dataclass + `compute(bars, period) -> EMAState`
2. Add `ema: EMAState | None` to `IndicatorSnapshot` in `engine.py`
3. Call `compute()` inside `IndicatorEngine.update()`
4. Expose in `strategy/context.py` → `ctx.indicators.ema`

**Debug warmup failure:** Check MongoDB `market_bars` has data for the security+timeframe. Warmup logs `indicator_warmup_failed` to structlog with exc detail.
