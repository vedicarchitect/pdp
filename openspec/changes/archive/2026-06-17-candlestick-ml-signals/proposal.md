## Why

The platform reads price through deterministic indicators (SuperTrend + the `indicator-suite`
families) and reads options through `options-analytics` (max-pain, PCR, GEX). What it cannot do
today is **learn** — there is no component that combines candlestick structure, classical
chart patterns, and indicator state into a *probabilistic forecast* of what price does next, and
nothing that improves from historical outcomes.

We want a **machine-learning signal that learns from candlestick patterns and price structure**.
Two things are missing before that is possible:

1. **Feature families** the model needs are not yet in the suite — there is no candlestick-pattern
   detector, no Elliott-Wave structure read, no Fibonacci retracement/extension levels (the suite
   has Fibonacci *pivots*, which are different), and no Elder Impulse regime (which needs a MACD
   tracker the suite also lacks).
2. **A learning layer** — an offline trainer over the MongoDB `market_bars` warehouse, a versioned
   model artifact, and a read-only online inference signal strategies can consume like any other
   indicator.

This change is **paper-first, additive, and phased**. Phase 1 delivers a general next-bar/next-session
**directional probability**; phase 2 layers an **expiry-day close-zone** head that also consumes
`options-analytics` features (max-pain/PCR/GEX/VIX). It does not change any existing strategy's
behaviour — the ML signal is opt-in, and existing indicators/strategies are untouched.

## What Changes

- **New indicator families** added to the `indicator-suite` (Rule #4: computed once, consumed
  read-only, never recomputed by strategies):
  - **Candlestick patterns** — deterministic per-bar detection (doji, hammer, shooting-star,
    bullish/bearish engulfing, harami, morning/evening star, marubozu, …).
  - **Elliott-Wave structure** — ZigZag/swing-pivot detection feeding a heuristic wave labeler
    (impulse 1–5 / corrective A–B–C) with a confidence score. Heuristic, opt-in, feature-only.
  - **Fibonacci retracement/extension** — levels from the latest swing leg (0.236/0.382/0.5/
    0.618/0.786 retracements; 1.272/1.618/2.0 extensions) and price's signed distance to the
    nearest level. Distinct from the existing Fibonacci *pivot* levels.
  - **Elder Impulse** — 13-EMA slope × MACD-histogram slope → per-bar regime (green/red/blue).
    Adds a reusable **MACD `*Tracker`** to the suite.
- **New `candlestick-ml-signals` capability** — a `src/pdp/ml/` package:
  - **Feature builder** — assembles a leakage-safe feature matrix (Polars) from `market_bars`:
    candlestick flags + Elliott/Fibonacci/Elder + existing suite snapshots (EMA/RSI/SuperTrend/
    pivots/VWAP/…). Identical builder runs offline (training) and online (inference).
  - **Offline trainer** — classical gradient-boosted trees (LightGBM, CPU). Walk-forward /
    purged time-series CV, forward-return-bucket labels, versioned artifact written to disk.
  - **Online inference** — loads the artifact and exposes a read-only directional probability
    via a new `IndicatorReader` accessor (`ctx.indicators.ml_signal(sid, tf)`), published to
    Redis (`ml:{sid}:{tf}`) mirroring the suite publish; non-blocking on the hot path.
  - **Backtest parity** — the same feature builder + artifact run in the backtest engine so
    live and backtest signals match.
  - **Phase 2 expiry head** — a second model consuming option-chain analytics features to
    classify the expiry-day close zone.
- **`task ml:train`** Taskfile target to (re)train and version artifacts.

## Capabilities

### New Capabilities

- `candlestick-ml-signals`: offline-trained, classical-ML directional/expiry signal that learns
  from candlestick patterns and price structure, served read-only online and reproducibly in
  backtest.

### Modified Capabilities

- `indicator-suite`: four new families (candlestick patterns, Elliott-Wave structure, Fibonacci
  retracement/extension, Elder Impulse) plus a shared MACD tracker; additive and opt-in.
- `strategy-config`: watchlist entries may opt into the ML signal (mirrors the existing
  `indicators: [...]` selection).

## Impact

- `src/pdp/indicators/` — new trackers: `candlestick.py`, `elliott.py`, `fib_levels.py`,
  `macd.py`, `elder_impulse.py`; register each in `registry.py`; extend `snapshot.py` and the
  `IndicatorReader` accessors in `strategy/context.py`. SuperTrend and existing families unchanged.
- `src/pdp/ml/` (new) — `features.py` (shared builder), `train.py` (trainer + CV), `infer.py`
  (artifact loader + online signal), `registry.py` (feature/label schema + artifact versioning),
  `labels.py`.
- `src/pdp/strategy/context.py` — add `ml_signal(sid, tf)` read-only accessor.
- `src/pdp/market/router.py` — publish `ml:{sid}:{tf}` after `on_bar`, mirroring the suite publish.
- `src/pdp/backtest/` — wire the same feature builder + artifact for parity.
- `Taskfile.yml` — `ml:train` target. `pyproject.toml` — add `lightgbm` (CPU) dependency.
- `settings.py` — ML defaults (model path, horizon, enable flag). `src/pdp/indicators/CLAUDE.md`
  and `src/pdp/ml/CLAUDE.md` — document new families and the pipeline.
- Tests — `tests/indicators/` for each new tracker; `tests/ml/` for feature leakage, label
  alignment, train/infer round-trip, and backtest↔live parity.
- No changes to existing strategy trading logic; signal is opt-in; paper-first.
