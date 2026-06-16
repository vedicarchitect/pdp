## 1. Framework

- [x] 1.1 Add `src/pdp/indicators/registry.py` mapping family name → `(tracker factory, default params)`
- [x] 1.2 Add `src/pdp/indicators/snapshot.py` with a `Snapshot` bundle holding the latest `*State` per family
- [x] 1.3 Rework `IndicatorEngine` (`engine.py`) to hold a per-`(security_id, timeframe)` bundle built from config; `on_bar(bar)` updates only that bundle's trackers and caches the snapshot
- [x] 1.4 Keep `get(sid, tf)` returning SuperTrend and `seed_from_bars()` behaviour for backward compatibility; add `get_snapshot(sid, tf)` + per-family getters
- [x] 1.5 Extend `IndicatorReader` (`strategy/context.py`) with read-only accessors (`ema`, `rsi`, `psar`, `vwap`, `vwma`, `pivots`, `fvg`, `market_profile`, `volume_profile`) and `snapshot(sid, tf)`; leave `supertrend(...)` unchanged
- [x] 1.6 Add optional `indicators: [...]` (with per-family params) to the watchlist schema (`strategy/registry.py`); build the engine in `main.py` from the union of all strategies' requests per `(sid, tf)`
- [x] 1.7 Publish the snapshot to Redis (`ind:{sid}:{tf}`) in `TickRouter` after `on_bar`, mirroring the SuperTrend publish; no blocking
- [x] 1.8 Add suite defaults to `settings.py`; update `src/pdp/indicators/CLAUDE.md`

## 2. Cheap O(1) indicators (float64)

- [x] 2.1 `ema.py` — `EMATracker` (multi-period 9/20/50/100/200) + `EMAState`
- [x] 2.2 `rsi.py` — `RSITracker` (Wilder running avg gain/loss) + `RSIState`
- [x] 2.3 `psar.py` — `ParabolicSARTracker` (EP/AF flip) + `ParabolicSARState`
- [x] 2.4 `vwap.py` — `VWAPTracker` (running ΣPV/ΣV, session reset) + `VWAPState`
- [x] 2.5 `vwma.py` — `VWMATracker` (rolling window ΣPV/ΣV over a bounded ring buffer) + `VWMAState`

## 3. Session & pattern indicators

- [x] 3.1 `pivots.py` — `PivotTracker` computing standard, Camarilla (pivot/R3/R4/S3/S4), and Fibonacci levels from the prior-session HLC, constant intrabar + `PivotState`
- [x] 3.2 `fvg.py` — `FVGTracker` (3-bar gap detection, list of unfilled gaps) + `FVGState`

## 4. Heavy / opt-in histograms

- [x] 4.1 `volume_profile.py` — `VolumeProfileTracker` (price-bucketed volume, POC/VAH/VAL, session reset) + `VolumeProfileState`
- [x] 4.2 `market_profile.py` — `MarketProfileTracker` (TPO into price buckets, session reset) + `MarketProfileState`
- [x] 4.3 Gate both behind explicit config opt-in so they never run for un-requested instruments

## 5. Warmup + backtest parity

- [x] 5.1 Extend `warm_up_indicator_engine` so seeded bars prime every configured family; derive prior-session HLC for pivots (reuse `_prior_trading_day` / session-start logic); keep failures non-fatal
- [x] 5.2 Make `backtest/sim.py` reuse the same tracker classes for any suite indicator a strategy reads; leave the SuperTrend path untouched

## 6. Tests & validation

- [x] 6.1 Unit per family against known fixtures (EMA hand-computed, RSI=Wilder, SAR flip, Camarilla/Fib/standard pivots from known HLC, VWAP session reset, VWMA window, FVG synthetic gap, Volume Profile POC/VAH/VAL)
- [x] 6.2 Config-driven selection test: requesting `[ema, rsi]` builds no profile/pivot trackers; `snapshot()` returns those two and `None` elsewhere
- [x] 6.3 Parity test: same bar series through live engine and backtest trackers yields identical states
- [x] 6.4 Latency/scale micro-benchmark: `engine.on_bar` across 200+ simulated `(sid, tf)` bundles; assert sub-millisecond mean update
- [x] 6.5 `openspec validate add-indicator-suite --strict`; `task test` / `task lint` / `task typecheck` green
