# Tasks — indicator-history-depth

> **Prerequisite:** `bar-session-anchoring` must be applied and `market_bars` rebuilt first.
> Backfilling depth into mis-anchored buckets deepens the error. Verify with:
> `git log --oneline -1 -- backend/pdp/market/bars.py` and confirm `_session_open_utc` exists.

## 1. Tests first (they fail on today's code)
- [ ] 1.1 `tests/indicators/test_ema.py`: an `EMATracker` configured for period 200 that has consumed
      150 bars → `state.values` has no key `200`; after 200 bars → key present
- [ ] 1.2 `tests/indicators/test_warmup.py`: required bars for `max(period)=200` is 1000
      (`5 × 200`); for `max(period)=14` it is 200 (the floor)
- [ ] 1.3 Warmup on an unknown timeframe (`"7m"`) raises, naming the timeframe
- [ ] 1.4 Warmup that finds 150 of 1000 bars emits exactly one `indicator_warmup_short` carrying
      `bars_found=150, bars_needed=1000`
- [ ] 1.5 `tests/strategies/test_config_parity.py`: for each of nifty/banknifty/sensex, the `ema`
      periods in `backend/strategies/directional_strangle_<u>.yaml` equal those in
      `backend/backtest/configs/strangle_<u>_hedged.yaml`

## 2. Configs — add period 200
- [ ] 2.1 `backend/strategies/directional_strangle_nifty.yaml:20` → `periods: [9, 20, 50, 100, 200]`
- [ ] 2.2 Same for `directional_strangle_banknifty.yaml` and `directional_strangle_sensex.yaml`
- [ ] 2.3 Same for `backend/backtest/configs/strangle_{nifty,banknifty,sensex}_hedged.yaml`
- [ ] 2.4 Confirm no other config references the `ema` family with a different period set

## 3. Derive the warmup window
- [ ] 3.1 `backend/pdp/indicators/warmup.py`: add
      `required_bars(indicators: list[dict]) -> int = max(200, 5 * max_period)`
- [ ] 3.2 Add `lookback_days(timeframe, required_bars) -> int` using `_TF_SESSION_BARS` plus a
      weekend/holiday pad (`× 7 / 5`, rounded up)
- [ ] 3.3 Delete `_TF_WARMUP_CALENDAR_DAYS` (`warmup.py:51-61`) and `_DEFAULT_WARMUP_CALENDAR_DAYS:62`;
      fix the two call sites at `:111` and `:148`
- [ ] 3.4 An unknown timeframe raises `ValueError(timeframe)` instead of defaulting to 1 day
- [ ] 3.5 Update `tests/indicators/test_warmup.py:251-291`, which imports the deleted constants

## 4. Converged-only reporting
- [ ] 4.1 `backend/pdp/indicators/ema.py`: track bars consumed; omit a period from `values` until
      `bars_seen >= period`
- [ ] 4.2 Audit the other families for the same premature-value problem (`rsi`, `macd`, `vwma`,
      `period_levels`); fix or file follow-ups — do not silently leave one wrong
- [ ] 4.3 `warmup.py`: emit one `indicator_warmup_short` per `(sid, tf, family)` with
      `bars_found` / `bars_needed`

## 5. Backfill depth
- [ ] 5.1 `backend/scripts/backfill_market_bars.py`: for each `WAREHOUSE_UNDERLYINGS` × configured TF,
      compute `required_bars` and count existing `market_bars` docs
- [ ] 5.2 Derive missing 15m/30m/1H from the stored 1m series (reuse the `bar-session-anchoring`
      rebuild helper — do not reimplement bucket maths)
- [ ] 5.3 Fall back to Dhan historical only where 1m coverage is absent; log which windows required it
- [ ] 5.4 Exit non-zero, naming `(sid, tf, found, needed)`, when depth cannot be reached
- [ ] 5.5 Run it; record final per-`(sid, tf)` bar counts in this change's README

## 6. Startup depth summary
- [ ] 6.1 `backend/pdp/indicators/engine.py`: after warmup, produce
      `{(sid, tf, family, period): seeded: bool}`
- [ ] 6.2 Strategy host logs one summary line per strategy naming unseeded combinations
- [ ] 6.3 Unit: a partially-seeded engine reports exactly the unseeded combinations

## 7. Measure the cost
- [ ] 7.1 Time warmup before and after; record both numbers
- [ ] 7.2 If boot exceeds the acceptable budget, seed the strategy's own timeframes synchronously and
      the remainder in a background task — never block the tick hot path
- [ ] 7.3 Confirm tick→WS p99 ≤ 50ms is unaffected (non-negotiable #5)

## 8. Verify against Kite
- [ ] 8.1 Compare 15m/30m/1H EMA(20/50/200) for NIFTY against the Kite matrix for five sessions
- [ ] 8.2 Document any residual delta and its cause; a delta that survives both this change and
      `bar-session-anchoring` is a *new* finding and needs its own change

## 9. Docs + validation
- [ ] 9.1 Delete the "EMA200 = `--` → increase `_TF_WARMUP_CALENDAR_DAYS` to 180+ days" row from the
      root `CLAUDE.md` troubleshooting table — it is wrong; the period was never configured
- [ ] 9.2 `backend/pdp/indicators/CLAUDE.md`: document `required_bars`, the convergence rule, and
      what `--` now means
- [ ] 9.3 Re-run the three strangle backtests; compare against the post-anchoring baseline
- [ ] 9.4 `task test` green against the recorded baseline
- [ ] 9.5 `openspec validate --strict indicator-history-depth` passes
