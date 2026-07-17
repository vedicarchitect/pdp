# Indicators Module

## Files

| File | Role |
|------|------|
| `engine.py` | `IndicatorEngine` — per-`(sid, tf)` SuperTrend + suite tracker bundle. Call `on_bar(bar)` on each closed bar. `get_supertrend_variants(sid, tf)` returns the 3-way `MATRIX_ST_VARIANTS` (`(10,2)`/`(10,3)`/`(3,1)`) bundle used by the execution-console indicator matrix (`indicator-matrix-kite-parity`). |
| `levels_store.py` | PMH/PML and week/month session-HLC levels for the execution console. `_session_window_hlc`/`_session_anchored_hlc` compute each day's high/low/close independently over the session window (reusing `market/bars.py::_session_open_utc`) rather than a naive calendar-range MIN/MAX — fixes a Kite-parity bug where straddling a session boundary corrupted PMH/PML. |
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
| `period_levels.py` | `PeriodLevelsTracker` / `PeriodLevelsState` — previous-day/week/month high-low (PDH/PDL, PWH/PWL, PMH/PML); frozen at day/ISO-week/month boundary; seeded from trailing ~40d of `market_bars` via `engine.seed_period_levels_history`. |
| `fvg.py` | `FVGTracker` / `FVGState` — 3-bar gap detection + fill tracking. |
| `volume_profile.py` | `VolumeProfileTracker` / `VolumeProfileState` — POC/VAH/VAL (opt-in). |
| `market_profile.py` | `MarketProfileTracker` / `MarketProfileState` — TPO per session (opt-in). |
| `macd.py` | `MACDTracker` / `MACDState` — fast/slow EMA lines + signal EMA + histogram (default 12/26/9). |
| `candlestick.py` | `CandlestickTracker` / `CandlestickState` — per-bar single/multi-bar pattern detection (doji, hammer, shooting-star, engulfing, harami, morning/evening star, marubozu) + bullish/bearish/neutral signal code. |
| `elliott.py` | `ElliottWaveTracker` / `ElliottWaveState` — ZigZag swing-pivot detection + heuristic 1–5/A–B–C wave labeler with confidence score. Heuristic and feature-only. |
| `fib_levels.py` | `FibLevelsTracker` / `FibLevelsState` — retracements (0.236/0.382/0.5/0.618/0.786) and extensions (1.272/1.618/2.0) from the latest swing leg; nearest level + signed distance. Distinct from `pivots.py` Fibonacci pivot levels. |
| `elder_impulse.py` | `ElderImpulseTracker` / `ElderImpulseState` — 13-EMA slope × MACD-histogram slope → green/red/blue regime; depends on `MACDTracker`. |
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

**Backtest parity for suite indicators:** `StrategyConfig.suite_indicators` (list of family dicts, default `[]`) gates which families `sim.py` builds and replays per bar. The resulting `Snapshot` is available as `_suite_snap` in the series loop. Note this applies to `sim.py`'s generic index backtest only — `StrangleConfig` (the directional-strangle backtest) has no `suite_indicators` field; its EMA input is a separate, hardcoded 9/20/50 alignment vote (`pdp/signals/bias.py`), sharing `EMATracker` and the `tf_ema_from_values()` conversion with live but not the period-200 console concept.

## Warmup depth (`indicator-history-depth`, 2026-07-12)

A period is missing from a tracker's state for exactly one of two reasons, and the fix is
different for each:

1. **Not configured** — the watchlist's `indicators:` never asked for it (e.g. `ema` declared
   `periods: [9, 20, 50, 100]`, no 200). `EMATracker` computes exactly the periods it is given;
   nothing seeds a period that isn't in the list. Fix: add the period to the YAML.
2. **Not yet converged** — configured, but the tracker hasn't consumed enough bars yet.
   `EMATracker.update()` already omits an unconverged period from `values` rather than
   reporting a partial/wrong number (same is already true of RSI's `ma`, and of MACD/VWMA,
   which return `None` entirely until seeded) — so `--` in the console means "genuinely not
   available yet", never "silently wrong".

`warmup.py::required_bars(indicators)` derives how many bars warmup needs: `5 x max(period)`
across every period-like key (`periods`, `period`, `ma_period`, `fast`, `slow`, `signal`, ...)
in every configured family, floored at 200. `lookback_days(timeframe, bars_needed)` converts
that to a calendar window using `_TF_SESSION_BARS` plus a weekend/holiday pad. Widening a
config's largest period widens the warmup window automatically — there is no hand-maintained
calendar-day table to keep in sync (`_TF_WARMUP_CALENDAR_DAYS` was deleted; it silently
defaulted an unlisted timeframe to a 1-day lookback, and its ">> 200 bars" assumption broke
the moment a period grew past what the table's margin assumed).

If `market_bars` doesn't hold `required_bars()` bars for a `(sid, tf)`, warmup logs one
`indicator_warmup_short` per `(sid, tf, family)` naming `bars_found`/`bars_needed`, and
`IndicatorEngine.seeding_summary(sid, tf)` reports the same gap as `{(family, period): False}`
— surfaced once per strategy at startup as `indicator_seeding_summary`
(`pdp/runtime/groups.py`), so an unseeded EMA(200) is visible in the boot log, not just as a
`--` discovered later in the console. Run `scripts/backfill_market_bars.py` to close a
depth gap — it derives 15m/30m/1H from the stored 1m series (reusing
`scripts/oneoff/rebuild_market_bars.py`'s session-anchored rollup) and falls back to Dhan
only for windows where 1m coverage itself is absent.

## Same-day Dhan fetch contract (`dhan-same-day-data`, confirmed 2026-07-13)

`warmup.py::_fetch_from_dhan` sets `to_date = today` (IST), so the Dhan top-up fetch always *asks*
for the current, possibly in-progress session. Live-probed 2026-07-13 11:30 IST
(`scripts/oneoff/probe_dhan_same_day.py`):

- **Intraday (`intraday_minute_data`, 5m and presumably 15m/30m/1H):** Dhan **does** return a
  still-forming final candle for the in-progress bucket — the probe's last candle (`bar_time`
  11:30:00, queried at 11:30:37) had real, distinct OHLC but volume ~10x lower than its neighbors
  (429,514 vs 2.5M-11.5M), the classic partial-candle fingerprint.
- **Daily (`historical_daily_data`, 1D/1w):** Dhan returns **nothing** for the current, in-progress
  trading day — `todays_candle_count=0`. No in-progress daily candle exists to accidentally persist.

See `openspec/changes/dhan-same-day-data/README.md` for the full probe output and reasoning.

Because of the intraday answer, `pdp/market/bars.py::bar_is_complete(bar_time, timeframe, now)` is
enforced unconditionally: any bar whose period hasn't fully elapsed (`bar_time + period > now`) is
dropped by `_fetch_from_dhan` before it can reach `_persist_bars` or seed a tracker — so a
still-forming final candle can never be written into `market_bars`, independent of whether Dhan
itself would have returned one. The same guard is applied everywhere else a broker fetch writes
`market_bars`: `scripts/backfill_spot.py` and `scripts/backfill_vix.py` (both default to
`--to date.today()`).

IST trading-day boundaries in `warmup.py` are computed via `datetime.now(ZoneInfo("Asia/Kolkata"))`,
not a fixed `+5:30` offset — the ~18 other fixed-offset IST derivations elsewhere in `pdp/` are
left as-is; they're bit-identical to `ZoneInfo` since India has no DST, not merely "safe today."
