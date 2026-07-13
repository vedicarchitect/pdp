# indicator-history-depth

## Why

EMA(200) renders as `--` in the execution console during live sessions, and the indicator matrix
disagrees with Kite across timeframes. Two separate causes, and the widely-repeated one is wrong.

**Cause 1 — the strategy never asks for EMA 200.** All three live configs
(`backend/strategies/directional_strangle_{nifty,banknifty,sensex}.yaml`) declare:

```yaml
      - family: ema
        periods: [9, 20, 50, 100]
```

`EMATracker` computes exactly the periods it is given. Nothing seeds a 200-period EMA, so nothing
can report one. No amount of warmup fixes a period that was never configured. The console asks for
`ema.values.get(200)`, gets `None`, and prints `--`. The project troubleshooting table in
`CLAUDE.md` attributes this to "warmup insufficient — increase `_TF_WARMUP_CALENDAR_DAYS` to 180+
days"; that advice is wrong and should be removed.

**Cause 2 — warmup windows are calendar-day guesses, and the data may not be there.**
`pdp/indicators/warmup.py:51` hand-tunes a `_TF_WARMUP_CALENDAR_DAYS` map (15m→40, 30m→45, 1H→90,
1D→400). Those windows are *nominally* generous — 40 calendar days × 25 bars/session comfortably
exceeds 200 bars — but three things make them fragile:

- The constants encode an assumption (`>= 200 bars`) that no longer holds the moment a config adds a
  longer period. They must be *derived* from `5 × max(period)` over the configured families, not
  hand-maintained next to a comment claiming ">> 200".
- A generous window is worthless if `market_bars` does not actually contain that history. Warmup
  seeds from Mongo and silently succeeds with whatever it finds; a 15m series with 60 stored bars
  yields an EMA(50) that is still converging and an EMA(100) that is meaningless, with no signal to
  the operator that the value is unreliable.
- `_DEFAULT_WARMUP_CALENDAR_DAYS = 1` means any timeframe *absent* from the map (a config typo, a
  new TF) silently warms up on a single day of data.

Together these explain the residual EMA disagreement with Kite that survives the bucket-anchoring
fix: our EMAs are seeded from too few bars and are still converging when the session starts.

This change must land **after** `bar-session-anchoring`. Backfilling more history into mis-anchored
buckets deepens the error rather than fixing it.

## What Changes

- **Add period 200** to the `ema` family in all three live strangle configs, and to the
  corresponding backtest configs so live and backtest stay in parity.

- **Derive the warmup window instead of hand-tuning it.** For each `(security_id, timeframe)`,
  compute the required bar count as `5 × max(period)` across the configured indicator families
  (floor 200), then convert to calendar days using the existing `_TF_SESSION_BARS` map with a
  weekend/holiday pad. Delete `_TF_WARMUP_CALENDAR_DAYS`. Raise on an unknown timeframe rather than
  falling back to one day.

- **Backfill `market_bars` to the required depth.** For every `(warehoused underlying, configured
  timeframe)`, ensure at least `5 × max(period)` bars exist — approximately 1200 bars per timeframe
  at the 200-period setting. Derive 15m/30m/1H from the 1m series where 1m coverage exists (free,
  reproducible); fall back to Dhan historical only for windows where 1m is absent.

- **Refuse to report an unconverged indicator.** `EMAState.values` omits a period until it has
  consumed at least that many bars, so the console shows `--` because the value is genuinely
  unavailable, never because it is silently wrong. Warmup emits one `indicator_warmup_short` warning
  per `(sid, tf, family)` that could not reach its required depth, naming bars found vs bars needed.

- **Assert depth at startup, not at first render.** A startup check logs a single summary line per
  strategy: which `(sid, tf, family, period)` combinations are fully seeded and which are not. A live
  session that begins with an unseeded EMA(200) is visible in the first hundred lines of the log.

## Impact

- **Affected specs:** `indicator-history-depth` (new). Amends `openspec/specs/indicators/spec.md`.
- **Affected code:** `backend/pdp/indicators/warmup.py` (derive window, delete
  `_TF_WARMUP_CALENDAR_DAYS`, `indicator_warmup_short`), `backend/pdp/indicators/ema.py` (omit
  unconverged periods), `backend/pdp/indicators/engine.py` (startup depth summary),
  `backend/strategies/directional_strangle_*.yaml` (+ period 200),
  `backend/backtest/configs/strangle_*.yaml` (+ period 200),
  `backend/scripts/backfill_market_bars.py`, `CLAUDE.md` (delete the wrong troubleshooting row).
- **Warmup gets slower.** Seeding ~1200 bars per `(sid, tf)` instead of the current ~200–700 lengthens
  startup. Measure it; if it exceeds the acceptable boot budget, seed the strategy's own timeframes
  synchronously and the rest in a background task, never blocking the hot path.
- **Backtest parity.** Adding period 200 to live configs but not backtest configs would silently
  diverge the two. Both move together, and the strangle backtests are re-run afterwards.
- **Depends on `bar-session-anchoring`.** Sequence: anchor, rebuild, *then* backfill depth. Ties
  into [[execution_console_accuracy]] and [[indicator_suite]].
- **A `--` in the console will become meaningful.** Today it means "period not configured"; after
  this change it means "not enough bars yet", which is an actionable operator signal.
