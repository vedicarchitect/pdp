# signals/ — Bias-Scoring Engine

## Files

| File | Role |
|------|------|
| `bias.py` | Pure, deterministic multi-input weighted vote → bucket → PE:CE ratio. No I/O, no globals — shared by `pdp.strategies.directional_strangle` (live) and `pdp.backtest.strangle_loader` (backtest), so identical inputs produce identical decisions on both paths. |

## The eight bias inputs

`score_bias(inp: BiasInputs, weights: BiasWeights)` combines up to eight signals into one
normalised score in `[-1, +1]`. Each has a weight (`BiasWeights.w_*`) and a data prerequisite —
if the prerequisite isn't met, the input is `None` and `score_bias` treats it as a silent
abstention (renormalises the weighted average over whatever *is* present).

| Input | Weight | Data source | Prerequisite |
|-------|--------|--------------|---------------|
| `ema_1h` | `w_ema_1h` | `ind.ema(sid, "1H")` | `1H` timeframe + `ema` family in watchlist |
| `ema_15m` | `w_ema_15m` | `ind.ema(sid, "15m")` | `15m` timeframe + `ema` family |
| `ema_5m` | `w_ema_5m` | `ind.ema(sid, "5m")` | `5m` timeframe + `ema` family |
| `cam_daily` | `w_cam_daily` | `ind.pivots(sid, "1D")` | `1D` timeframe + `pivots` family |
| `cam_weekly` | `w_cam_weekly` | `ind.pivots(sid, "1w")` | `1w` timeframe + `pivots` family (own watchlist entry — see below) |
| `swing` (pdh/pdl/pwh/pwl) | `w_swing` | `ind.period_levels(sid, tf)` | `period_levels` family on **any** configured timeframe (`PeriodLevelsTracker` accumulates day/week high-low from whatever bars it's fed and freezes at the boundary — correct regardless of which TF feeds it) |
| `orb` | `w_orb` | raw `15m` bar OHLC, tracked in the strategy itself | `15m` timeframe present (not a suite indicator — no `family` requirement) |
| `pcr` | `w_pcr` | `ctx.chain_hub.get_pcr(underlying)` | this underlying has a running options chain poller — see `pdp.strategy.registry.strategy_underlyings` |

## Abstention-saturation guards (`bias-ranking-hardening`, 2026-07-21)

Because the score renormalises over *present* inputs only, a starved input set (few votes present)
can saturate to an extreme far more easily than a full one — proven on 2026-07-21, when a backtest
whose higher-TF EMAs never warmed renormalised onto ORB+PCR alone (2.0 of 10.5 configured weight),
scored −1.000, and sold a naked `0 PE : 5 CE` (`COMPLETE_BEAR`). Two guards in `score_bias` make
this unreachable, protecting **both** backtest and live:

- **Quorum floor** (`BiasWeights.min_quorum_weight_frac`, default `0.25`). `present_weight_frac =
  Σ(present non-zero weights) / Σ(all configured non-zero weights)`. Below the floor, the bucket is
  forced `NEUTRAL` (1:1) regardless of score. The ORB+PCR-only case is `2.0/10.5 = 0.19 < 0.25` →
  neutral; a thin-but-trend-backed `ema_1h+pcr = 3.0/10.5 = 0.286` still scores normally.
  `present_weight_frac` is reported on `BiasResult` and in `reason` (`quorum=…`).
- **Extreme-bucket guard** (`_guard_extreme`). The two *naked* buckets `COMPLETE_BULL` (5:0) and
  `COMPLETE_BEAR` (0:5) are the only undefended positions in the ratio table. They are reachable
  only when `ema_1h` is present (non-abstaining) **and** agrees with the bucket's direction;
  otherwise the bucket downgrades to the nearest *defended* bucket (`MOST_BULL`/`MOST_BEAR`, 4:2 /
  2:4), which keeps a protective opposite side. (The follow-up `bias-ranking-multisignal` extends the
  agreement requirement to also include `st_1h`.)

Note these are a *backstop*: live already blocks entry on any unseeded indicator via
`DirectionalStrangle.check_readiness`, and the backtest now loads a spot-only warmup prefix
(`day_loader.load_window(warmup_days=…)`, driven per quarter-chunk by `strangle_run.py`) so its
higher-TF EMAs converge before the first traded day. The guards defend any path that still reaches
`score_bias` on a thin vote set.

## Startup satisfiability check (`bias-input-completeness`, 2026-07-12)

`check_bias_satisfiability(weights, watchlist, *, underlying, options_underlyings)` verifies
every non-zero weight above has its prerequisite, and raises `BiasInputUnsatisfiable` naming
the first unmet `(weight, requirement)` pair. A weight of `0` imposes no requirement. Wired
into `StrategyHost.start()` (gated on `isinstance(instance, DirectionalStrangle)`), called
right after the strategy instance is constructed — the raise propagates out of `start()`
uncaught, aborting strategy load.

This is the structural fix for a real incident: `cam_weekly` was permanently `None` (no
watchlist ever declared `1w`) and SENSEX's `pcr` was permanently `None` (SENSEX had no chain
poller), and nothing complained — `score_bias` just renormalised over fewer inputs, silently
biasing the score toward whatever the *other* inputs said. Two of the three dead inputs pulled
toward *neutral*, the most-traded bucket, so live traded measurably more neutral than its
own backtest for months. See `openspec/changes/archive/.../bias-input-completeness/README.md`
findings for the full incident writeup.

## Vote breakdown logging

`BiasResult.breakdown: dict[str, VoteBreakdown]` (`vote: int | None`, `weight: float`,
`abstained: bool`) covers all eight inputs on every evaluation, present or abstaining —
`DirectionalStrangle` emits it on every `bias_evaluated` event as a nested dict (queryable
field names in OpenSearch, e.g. `breakdown.cam_weekly.abstained`), not a formatted string. An
abstaining input is now visible in the session log directly, rather than inferred after the
fact from a suspicious bucket distribution.

## Weekly Camarilla needs its own watchlist entry

`WatchlistEntry.indicators` applies to *every* timeframe in that entry's `timeframes` list —
there's no per-timeframe indicator config. Adding `1w` to the same entry that carries
`ema/supertrend/psar/vwap/pivots/period_levels` would configure EMA(200) etc. on weekly bars
too (needing ~19 years of weekly history to converge, and disarming the strategy at every
startup via `StrategyHost.start()`'s `is_warm(sid, "1w", min_bars=200)` check). The live
configs instead declare a **second** watchlist entry for the same `security_id`, with
`timeframes: [1w]` and `indicators: [{family: pivots}]` only — `IndicatorEngine.configure_suite`
unions families per `(sid, tf)`, so this cleanly adds just weekly pivots. `StrategyHost.start()`
also exempts `tf == "1w"` from the 200-bar disarm check (weekly pivots seed from the single
most-recently-completed ISO week, not a 200-bar convergence count — 200 weekly bars is ~4
years, which BANKNIFTY/SENSEX don't have).

## Which underlyings get a chain poller (not a setting)

`pdp.strategy.registry.strategy_underlyings(strategies_dir)` is the union of every loaded
strategy YAML's `params.underlying`. `OptionsChainPoller` and `WarehouseService` are both
constructed with an explicit `underlyings` list computed this way, in `pdp/runtime/groups.py`,
`pdp/warehouse/__main__.py`, and `scripts/backfill_market_bars.py` — there is no
`OPTIONS_UNDERLYINGS`/`WAREHOUSE_UNDERLYINGS` env var. Declaring `params.underlying: SENSEX`
in a strategy YAML is the only step needed to bring SENSEX's chain and warehouse online.
