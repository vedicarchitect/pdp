# Design — candlestick-ml-signals

## Goals & non-goals

**Goals**
- Learn a probabilistic signal from candlestick patterns + price structure + existing indicators.
- Classical, interpretable, CPU-only ML (gradient-boosted trees) that backtests reproducibly.
- Strict no-lookahead so live and backtest agree and offline metrics are trustworthy.
- Additive: new feature families and an opt-in signal; zero change to existing strategy behaviour.

**Non-goals (this change)**
- Deep learning / sequence models, GPU, online/continual learning.
- Auto-trading on the signal — strategies opt in and decide; no new order path here.
- Replacing any existing indicator or strategy.

## Phasing

- **Phase 1 — directional head.** Predict the bucketed forward return over a configured horizon
  for a `(security_id, timeframe)` (e.g. P(up) / P(flat) / P(down)). Trained on `market_bars`.
- **Phase 2 — expiry-close head.** Predict NIFTY's expiry-day close *zone* (bucketed distance
  from spot), adding `options-analytics` features (max-pain, PCR, GEX, IV/VIX, OI walls). Reuses
  the same trainer/infer scaffolding; gated behind config.

## New indicator families (feature sources)

All are O(1)-per-bar stateful `*Tracker` + frozen `*State`, registered in
`indicators/registry.py`, opt-in via config, consumed read-only — exactly like the existing suite.

| Family | Tracker | State (key outputs) |
|---|---|---|
| Candlestick patterns | `CandlestickTracker` | per-pattern flags + a compact bullish/bearish/neutral code for the last bar |
| Elliott-Wave | `ElliottWaveTracker` | ZigZag swing pivots (configurable %/ATR threshold), heuristic wave label (1–5 / A–B–C), wave position, confidence |
| Fibonacci retr/ext | `FibLevelsTracker` | levels from the latest swing leg, nearest level, signed distance, last-reacted level |
| MACD (shared) | `MACDTracker` | macd, signal, histogram (fast/slow/signal periods) |
| Elder Impulse | `ElderImpulseTracker` | regime ∈ {green, red, blue}, EMA13 direction, MACD-hist direction |

Elliott-Wave labels are **heuristic and explicitly probabilistic** (counts are subjective) — they
are model *features*, never hard trading rules. Elder Impulse depends on `MACDTracker`, so MACD is
introduced as its own reusable family (also useful standalone).

## ML package layout (`src/pdp/ml/`)

| Module | Responsibility |
|---|---|
| `features.py` | The **single** feature builder. Given an ordered bar stream + per-bar suite snapshots, emit a feature row using only data ≤ that bar's close. Used identically offline and online. |
| `labels.py` | Forward-return bucketing (directional head) and expiry close-zone bucketing (expiry head). Labels computed only during training. |
| `train.py` | Load `market_bars` (Polars) → build features+labels → walk-forward / purged CV → fit LightGBM → write versioned artifact + a metrics/feature-importance report. |
| `infer.py` | Load the artifact once, produce `MLSignalState` (class probabilities + argmax + model version) from a live feature row. No training deps required at runtime if model is present. |
| `registry.py` | Feature schema + label schema + artifact path/version contract; guards train/infer schema drift. |

## No-lookahead (the load-bearing constraint)

- The feature builder consumes bars **in order** and may use only values known at or before the
  current bar's close (closed-bar suite snapshots, prior swings, prior session pivots). No future
  bar, no full-series transforms that peek ahead.
- Labels look forward by exactly the configured horizon and are dropped where the horizon is
  unavailable (end of series / session).
- CV is **purged walk-forward** with an embargo so train/validation folds don't leak across the
  label horizon.
- Same builder code path in `train.py`, `infer.py`, and the backtest ⇒ live = backtest = offline.

## Online serving & latency

- Inference reads the **already-computed** suite snapshot for `(sid, tf)`; it does not recompute
  indicators. Tree inference on one feature row is microseconds, but to protect the
  `tick→WS p99 ≤ 50ms` budget the signal is computed **after** `on_bar` caching and published to
  Redis (`ml:{sid}:{tf}`) like the suite snapshot; if a model is heavy it runs off the hot path.
- If no artifact is loaded, `ml_signal(sid, tf)` returns `None` (same contract as an unseeded
  indicator) — strategies degrade gracefully.

## Reproducibility & ops

- Artifacts are versioned on disk (model + feature/label schema + training window + git sha).
- `task ml:train` retrains and writes a new version; inference pins a configured version.
- Settings: model dir, active version, horizon, label buckets, enable flag — all via
  `get_settings()`.

## Alternatives considered

- **Deep sequence models (LSTM/transformer)** — rejected for now: heavier deps/GPU, harder
  parity and latency, less interpretable. Classical GBT on engineered candlestick/structure
  features is the pragmatic first cut; the feature contract leaves room to swap the estimator later.
- **Standalone ML module that re-derives indicators** — rejected: violates Rule #4 and risks
  live/backtest drift. We reuse the suite and add the missing families to it.
