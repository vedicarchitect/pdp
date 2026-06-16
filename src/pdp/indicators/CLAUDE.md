# Indicators Module

## Files

| File | Role |
|------|------|
| `engine.py` | `IndicatorEngine` — per-`(sid, tf)` SuperTrend + suite tracker bundle. Call `on_bar(bar)` on each closed bar. |
| `supertrend.py` | Pure `SuperTrendState` dataclass + `SuperTrendTracker`. Uses `Decimal`; unchanged. |
| `warmup.py` | `warm_up_indicator_engine()` — seeds engine from MongoDB `market_bars` on startup. |
| `snapshot.py` | `Snapshot` dataclass — bundles the latest `*State` per suite family for a `(sid, tf)`. |
| `registry.py` | Maps family name → `(tracker class, default params)`; `build_tracker(name, params)`. |
| `ema.py` | `EMATracker` / `EMAState` — multi-period EMA (default 9/20/50/100/200), float64 O(1). |
| `rsi.py` | `RSITracker` / `RSIState` — Wilder running-average RSI (default period 14) + EMA signal line (`RSIState.ma`, default ma_period 9). |
| `psar.py` | `ParabolicSARTracker` / `ParabolicSARState` — EP/AF flip SAR. |
| `vwap.py` | `VWAPTracker` / `VWAPState` — running ΣPV/ΣV, session-reset at session date boundary. |
| `vwma.py` | `VWMATracker` / `VWMAState` — rolling window ΣPV/ΣV via ring buffer. |
| `pivots.py` | `PivotTracker` / `PivotState` — standard/Camarilla/Fibonacci levels from prior HLC. |
| `fvg.py` | `FVGTracker` / `FVGState` — 3-bar gap detection + fill tracking. |
| `volume_profile.py` | `VolumeProfileTracker` / `VolumeProfileState` — POC/VAH/VAL (opt-in). |
| `market_profile.py` | `MarketProfileTracker` / `MarketProfileState` — TPO per session (opt-in). |
| `__init__.py` | Exports `IndicatorEngine`, `Snapshot`, `SuperTrendState`. |

## Rules

- **Never** add indicator compute logic inside a strategy class. Add to this module.
- `IndicatorEngine` is singleton per app — injected via `app.state.indicator_engine`.
- SuperTrend uses `Decimal` and is **unchanged**. All new families use `float64`.
- Suite trackers are selected per `(sid, tf)` via watchlist `indicators: [...]` config.
- Heavy trackers (`volume_profile`, `market_profile`) are opt-in only.
- Warmup reads from MongoDB `market_bars`; seeds every configured family including pivots.

## Key types

```python
# engine.py
class IndicatorEngine:
    def on_bar(self, bar: BarClosed) -> SuperTrendState | None: ...
    def get(self, sid, tf) -> SuperTrendState | None: ...          # backward-compat
    def seed_from_bars(self, bars) -> int: ...                     # backward-compat
    def configure_suite(self, sid, tf, indicators: list[dict]): ...
    def get_snapshot(self, sid, tf) -> Snapshot | None: ...
    def get_ema(self, sid, tf) -> EMAState | None: ...
    # ... one getter per family

# snapshot.py
@dataclass(slots=True)
class Snapshot:
    ema: EMAState | None
    rsi: RSIState | None
    psar: ParabolicSARState | None
    vwap: VWAPState | None
    vwma: VWMAState | None
    pivots: PivotState | None
    fvg: FVGState | None
    volume_profile: VolumeProfileState | None
    market_profile: MarketProfileState | None

# Tracker update protocol (all families share this signature):
tracker.update(high: float, low: float, close: float, volume: float, bar_time: datetime) -> State | None
```

## Adding a strategy that uses suite indicators

```yaml
# strategies/my_strategy.yaml
watchlist:
  - security_id: "13"
    exchange_segment: IDX_I
    timeframes: ["15m"]
    indicators:
      - family: ema
        periods: [9, 20, 50]
      - family: rsi
      - family: vwap
```

```python
# src/pdp/strategies/my_strategy.py
ema = ctx.indicators.ema(ctx.bar.security_id, ctx.bar.timeframe)
if ema is not None:
    fast = ema.values.get(9)
    slow = ema.values.get(20)
```

## Common Tasks

**Add a new indicator family:**
1. Create `new_family.py` with `NewFamilyTracker(high, low, close, volume, bar_time)` + `NewFamilyState`
2. Register in `registry.py`: `_register("new_family", NewFamilyTracker, defaults)`
3. Add `new_family: NewFamilyState | None = None` field to `Snapshot` in `snapshot.py`
4. Add `get_new_family()` to `IndicatorEngine` in `engine.py`
5. Add `new_family()` accessor to `IndicatorReader` in `strategy/context.py`
6. Add `"new_family"` to `_SUITE_FAMILIES` set in `engine.py`

**Debug warmup failure:** Check MongoDB `market_bars` has data for the security+timeframe. Warmup logs `indicator_warmup_failed` to structlog with exc detail. If suite trackers are missing for a `(sid, tf)` on startup (ordering bug — `configure_suite` must be called before warmup), warmup logs `indicator_warmup_suite_not_configured` at DEBUG.

**RSI signal line:** `RSIState.ma` holds an EMA of the RSI values (default `ma_period=9`). It is `None` until `ma_period` RSI values have been seen. Configure via `{"family": "rsi", "period": 14, "ma_period": 9}`. Redis snapshot publishes it as `rsi_ma` (flat float, separate from the `rsi` key — backward-compatible).

**Backtest parity for suite indicators:** `StrategyConfig.suite_indicators` (list of family dicts, default `[]`) gates which families `sim.py` builds and replays per bar. The resulting `Snapshot` is available as `_suite_snap` in the series loop.
