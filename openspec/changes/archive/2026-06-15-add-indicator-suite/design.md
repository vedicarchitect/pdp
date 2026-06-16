## Context

The live indicator layer today is a single `SuperTrendTracker` per `(security_id, timeframe)`
inside `IndicatorEngine` (`src/pdp/indicators/engine.py:21-63`), driven once per closed bar
from `TickRouter` (`src/pdp/market/router.py:112`) before strategy dispatch, and read
read-only through `IndicatorReader.supertrend(...)` (`src/pdp/strategy/context.py:28-37`).
SuperTrend uses `Decimal` for options-pricing precision and has validated live↔backtest
parity; backtest replays the same `SuperTrendTracker` (`src/pdp/backtest/sim.py:203`).

We are adding a full indicator suite as the single shared compute layer. The hard constraint
is scale: continuous WebSocket feeds for **200+ instruments** (options + futures + stocks +
indices) across multiple timeframes, with per-update cost in the **microsecond** range to stay
within the `tick→WS p99 ≤ 50ms` budget (CLAUDE.md rule #5). The suite must remain the sole
source of indicator values — strategies, backtest, and the UI consume it and never recompute
(rule #4).

## Goals / Non-Goals

**Goals:**
- One shared, config-driven compute layer covering EMA (9/20/50/100/200), RSI, Parabolic SAR,
  VWAP, VWMA, standard/Camarilla/Fibonacci pivots, FVG, Market Profile, Volume Profile —
  plus the existing SuperTrend.
- O(1)-per-bar `float64` updates that sustain 200+ instruments within the latency budget.
- Compute only what strategies request per `(instrument, timeframe)`; heavy histograms opt-in.
- Read-only consumption via `ctx.indicators`; backtest reuses the same trackers for parity.

**Non-Goals:**
- Changing SuperTrend's algorithm, precision (`Decimal`), or its live/backtest behaviour.
- Adding any new trading logic, order path, or strategy decisions (compute-only).
- Persisting indicator history to a database (only the latest snapshot is published to Redis).
- Implementing the code in this change — this proposal authors the OpenSpec artifacts only;
  implementation follows in a later change per `tasks.md`.

## Decisions

### 1. Numeric backend: float64 for new indicators, Decimal retained for SuperTrend
**Decision:** All new families compute on `float64` scalars/arrays with O(1) incremental
updates. SuperTrend keeps its existing `Decimal` implementation untouched.

**Rationale:** At 200+ instruments × ~12 families × multiple timeframes, `Decimal` arithmetic
(~10–50× slower per op) risks the microsecond/p99 budget. `float64` is sufficient for momentum
/ trend / level indicators. SuperTrend stays `Decimal` because its parity with backtest is
already validated and options-premium math there is precision-sensitive; migrating it is
unnecessary risk for this change.

**Alternatives considered:**
- A. Decimal everywhere — uniform/precise but likely misses the latency budget at scale.
- C. Hybrid by data type — more nuance than needed; new indicators don't touch premium math.

### 2. Config-driven selection per (instrument, timeframe)
**Decision:** Each watchlist entry declares an optional `indicators: [...]` list (with
per-family params, e.g. EMA periods, profile bucket size). The engine builds, per
`(security_id, timeframe)`, only the **union** of families requested by all strategies on that
pair. Unrequested families incur no allocation and no per-bar cost. Market/Volume Profile are
opt-in.

**Rationale:** Computing every family (especially price-bucketed profiles) for every one of
200+ instruments every bar is wasteful; most instruments need only a few cheap indicators.
Config-driven selection keeps the hot path proportional to actual demand.

**Alternatives considered:**
- B. Compute everything always — simplest mental model, heaviest cost; profiles for 200
  instruments could dominate.
- D. Tiered (cheap-always, heavy-on-demand) — viable, but a single uniform config knob is
  simpler and still lets cheap families be requested broadly.

### 3. Engine as a per-(sid, tf) tracker bundle + registry
**Decision:** Rework `IndicatorEngine` to hold a **bundle** of trackers per `(sid, tf)` instead
of a single SuperTrend. A `registry.py` maps family name → `(tracker factory, default params)`.
`on_bar(bar)` updates only that bundle's trackers and caches a `Snapshot`. Add
`get_snapshot(sid, tf)` and per-family getters; **keep `get(sid, tf)` returning SuperTrend**
for backward compatibility. `seed_from_bars()` already drives `on_bar`, so warmup primes every
configured family with no extra plumbing.

**Rationale:** A registry + bundle keeps the engine open for new families without touching the
hot loop, and preserves the existing public surface (`get`, `seed_from_bars`).

### 4. Session anchoring and pivot basis
**Decision:** VWAP and both profiles reset at session start (09:15 IST). Standard, Camarilla
(pivot/R3/R4/S3/S4), and Fibonacci pivots are derived once per session from the **prior
session HLC** and held constant intrabar. Reuse the existing session-aware prior-trading-day
logic in `warmup.py` (`_prior_trading_day`, `_SESSION_START_UTC_*`).

**Rationale:** These are by definition session constructs; computing prior-session HLC once per
day is O(1) and avoids per-bar work. Reusing warmup's calendar keeps holiday/weekend handling
in one place.

### 5. Hot-path publish + consumption
**Decision:** After `engine.on_bar(bar)` in `TickRouter`, publish the snapshot to Redis
(`ind:{sid}:{tf}`) for the WS hub/UI, mirroring the existing SuperTrend publish — non-blocking.
Strategies consume via new read-only `IndicatorReader` accessors (`ema`, `rsi`, `psar`, `vwap`,
`vwma`, `pivots`, `fvg`, `market_profile`, `volume_profile`) plus `snapshot(sid, tf)`.

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| **Latency regression** — adding families to the hot path could blow the p99 budget. | float64 O(1) updates; config-driven so only requested families run; profiles opt-in; latency micro-benchmark across 200+ bundles asserts sub-millisecond mean `on_bar`. |
| **Memory growth** — profiles keep price-bucketed arrays per `(sid, tf)`. | Profiles are opt-in via config; bucket size/range bounded by params; reset per session. |
| **Live↔backtest drift** — a strategy reading suite indicators could diverge if backtest recomputes differently. | Backtest reuses the exact tracker classes; a parity test feeds the same series through both paths and asserts identical states. |
| **Warmup gaps** — pivots need prior-session HLC which may be thin in Mongo. | Reuse existing Dhan fallback in warmup; missing data leaves the family cold (None) without raising, exactly as SuperTrend does today. |
| **Backward compatibility** — existing `ctx.indicators.supertrend(...)` callers. | Keep `IndicatorEngine.get()` and `IndicatorReader.supertrend()` behaviour unchanged; SuperTrend tracker untouched. |

## Verification

- Unit per family against known fixtures: EMA vs hand-computed series; RSI vs Wilder reference;
  Parabolic SAR flip on a known reversal; Camarilla R3/R4/S3/S4 and Fibonacci/standard pivots
  from a known prior HLC; VWAP reset across a session boundary; VWMA over a rolling window; FVG
  on a synthetic 3-bar gap; Volume Profile POC/VAH/VAL on a known distribution.
- Config-driven selection: an engine built for an instrument requesting only `[ema, rsi]`
  creates no profile/pivot trackers; `snapshot()` returns those two and `None` elsewhere.
- Parity: same bar series through the live engine and the backtest trackers yields identical
  states.
- Latency/scale: micro-benchmark `engine.on_bar` across 200+ simulated `(sid, tf)` bundles;
  assert mean update is sub-millisecond and well under the per-tick budget.
- `openspec validate add-indicator-suite --strict`; `task test` / `task lint` / `task typecheck`
  green.
