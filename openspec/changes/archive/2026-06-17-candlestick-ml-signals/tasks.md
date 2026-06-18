## 1. New indicator families (feature sources)

- [x] 1.1 `indicators/macd.py` — `MACDTracker` (fast/slow/signal EMAs) + `MACDState`
- [x] 1.2 `indicators/candlestick.py` — `CandlestickTracker` (doji, hammer, shooting-star, engulfing, harami, morning/evening star, marubozu) + `CandlestickState` with per-pattern flags and a bull/bear/neutral code
- [x] 1.3 `indicators/elliott.py` — `ElliottWaveTracker` (ZigZag swing pivots with %/ATR threshold + heuristic 1–5 / A–B–C labeler + confidence) + `ElliottWaveState`
- [x] 1.4 `indicators/fib_levels.py` — `FibLevelsTracker` (retracements 0.236/0.382/0.5/0.618/0.786, extensions 1.272/1.618/2.0 from the latest swing; nearest level + signed distance) + `FibLevelsState`
- [x] 1.5 `indicators/elder_impulse.py` — `ElderImpulseTracker` (13-EMA slope × MACD-hist slope → green/red/blue) + `ElderImpulseState`; depends on `MACDTracker`
- [x] 1.6 Register all five in `indicators/registry.py`; extend `indicators/snapshot.py` and the `IndicatorReader` accessors in `strategy/context.py`
- [x] 1.7 Unit tests in `tests/indicators/` for each tracker (known-pattern fixtures, O(1) update, unseeded → `None`)
- [x] 1.8 Update `src/pdp/indicators/CLAUDE.md`

## 2. ML package scaffolding (`src/pdp/ml/`)

- [x] 2.1 `ml/registry.py` — feature schema, label schema, artifact path/version contract, drift guard
- [x] 2.2 `ml/features.py` — the single leakage-safe feature builder (Polars) consuming ordered bars + per-bar suite snapshots; used identically offline and online
- [x] 2.3 `ml/labels.py` — forward-return bucketing (directional head) + expiry close-zone bucketing (expiry head)
- [x] 2.4 `settings.py` — ML defaults (model dir, active version, horizon, label buckets, enable flag); `src/pdp/ml/CLAUDE.md`
- [x] 2.5 Add `lightgbm` (CPU) to `pyproject.toml`; `uv lock`

## 3. Offline training (directional head)

- [x] 3.1 `ml/train.py` — load `market_bars` → build features+labels → purged/embargoed walk-forward CV → fit LightGBM → write versioned artifact + metrics/feature-importance report
- [x] 3.2 `task ml:train` Taskfile target
- [x] 3.3 Tests in `tests/ml/` — feature leakage (row *t* uses only ≤ *t*), label horizon dropping, CV embargo, train→artifact round-trip

## 4. Online inference + serving

- [x] 4.1 `ml/infer.py` — load artifact once, produce `MLSignalState` (class probs + argmax + version); schema-drift refusal → no signal
- [x] 4.2 `strategy/context.py` — `ctx.indicators.ml_signal(sid, tf)` read-only accessor; `None` when no model
- [x] 4.3 `market/router.py` — publish `ml:{sid}:{tf}` after `on_bar` caching, mirroring the suite publish; no blocking I/O on the hot path
- [x] 4.4 `strategy/registry.py` — watchlist opt-in (enable flag + model version); load only requested models
- [x] 4.5 Latency check: signal computation reuses the cached snapshot and stays within the tick→WS p99 ≤ 50ms budget

## 5. Backtest parity

- [x] 5.1 Wire the same `ml/features.py` builder + pinned artifact into `src/pdp/backtest/`
- [x] 5.2 Parity test: replay a bar sequence in backtest and live → signal matches at every bar

## 6. Phase 2 — expiry-close head

- [x] 6.1 Extend `ml/features.py` to optionally include `options-analytics` features (max-pain, PCR, GEX, IV/India VIX, OI walls) for the active NIFTY expiry
- [x] 6.2 `ml/labels.py` — expiry close-zone buckets (distance-from-spot); train a second artifact
- [x] 6.3 Gate the expiry head behind config (disabled by default); serve read-only like the directional head
- [x] 6.4 Tests — options-feature leakage + expiry-head round-trip

## 7. Validation

- [x] 7.1 `task openspec:validate -- candlestick-ml-signals` passes (strict)
- [x] 7.2 `task test` and `task lint` / `task typecheck` green for new modules
- [x] 7.3 Update `CLAUDE.md` module index with `src/pdp/ml/`
