# Tasks — bias-input-completeness

> **Prerequisites:** `bar-session-anchoring` and `indicator-history-depth` applied. Wiring an input
> to mis-anchored or under-seeded bars trades one silent error for another.

## 1. Tests first (they fail on today's code)
- [ ] 1.1 `tests/strategies/test_bias_inputs.py`: `_build_bias_inputs` requests pivots on `1D`, never
      on `5m` (assert with a spying `IndicatorReader`)
- [ ] 1.2 With a `1w` pivot tracker configured, `cam_weekly` is non-null
- [ ] 1.3 With `chain_hub.get_pcr("SENSEX")` stubbed to a float, `BiasInputs.pcr` is that float
- [ ] 1.4 `tests/strategy/test_bias_satisfiability.py`: `w_cam_weekly>0` + no `1w` in watchlist →
      startup raises, message contains `w_cam_weekly` and `1w`
- [ ] 1.5 `w_ema_1h>0` + `1H` entry without `ema` family → raises naming the family
- [ ] 1.6 `w_pcr>0` + underlying not in `OPTIONS_UNDERLYINGS` → raises naming the underlying
- [ ] 1.7 `w_cam_weekly=0.0` + no `1w` → startup succeeds
- [ ] 1.8 All three shipped configs pass the satisfiability check after task 3 lands
- [ ] 1.9 `tests/signals/test_bias.py`: a null input is recorded as `abstain` in the emitted breakdown

## 2. Fix the two mis-wired reads
- [ ] 2.1 `directional_strangle.py:696` → `pivot = ind.pivots(self.sid, "1D")`
- [ ] 2.2 `directional_strangle.py:703` — `period_levels` also reads `"5m"`; confirm whether PDH/PDL
      and PWH/PWL are correct from a 5m tracker. `PeriodLevelsTracker` freezes at day/week boundaries,
      so it may be correct on any TF. **Verify before changing; document the finding either way.**
- [ ] 2.3 Delete the stale comment at `:699` claiming the `1w` snapshot is "seeded by 1w BarAggregator"

## 3. Configs — add the `1w` watchlist entry
- [ ] 3.1 `backend/strategies/directional_strangle_{nifty,banknifty,sensex}.yaml`: add `1w` to
      `timeframes` and ensure `family: pivots` is present
- [ ] 3.2 Same for `backend/backtest/configs/strangle_{nifty,banknifty,sensex}_hedged.yaml`
- [ ] 3.3 Confirm `market_bars` holds enough `1w` bars for the pivot seed; if not, backfill (a 200-bar
      weekly seed is ~4 years). Record the counts.

## 4. SENSEX chain + warehouse
- [ ] 4.1 `backend/pdp/settings.py:87` → `OPTIONS_UNDERLYINGS: str = '["NIFTY","BANKNIFTY","SENSEX"]'`
- [ ] 4.2 **`backend/.env`: set `OPTIONS_UNDERLYINGS=["NIFTY","BANKNIFTY","SENSEX"]`.** The `.env`
      value wins; step 4.1 alone is a no-op. `.env` is not in git — this must be done on every target.
- [ ] 4.3 `backend/pdp/settings.py:113` → `WAREHOUSE_UNDERLYINGS: list[str] = ["NIFTY", "BANKNIFTY", "SENSEX"]`
- [ ] 4.4 Confirm the SENSEX chain poller starts and `get_pcr("SENSEX")` is non-null during market hours
- [ ] 4.5 Check the added chain-poll load against the Dhan rate limit before enabling in a live session

## 5. Startup satisfiability check
- [ ] 5.1 Define the requirement map once, next to `BiasWeights`:
      `w_cam_daily → ("1D", "pivots")`, `w_cam_weekly → ("1w", "pivots")`,
      `w_ema_1h → ("1H", "ema")`, `w_ema_15m → ("15m", "ema")`, `w_ema_5m → ("5m", "ema")`,
      `w_swing → (any, "period_levels")`, `w_orb → (intraday, —)`,
      `w_pcr → underlying ∈ OPTIONS_UNDERLYINGS`
- [ ] 5.2 `backend/pdp/strategy/host.py`: at load, for each weight > 0, assert its requirement;
      raise naming `(weight, missing requirement)`
- [ ] 5.3 The raise must abort startup — verify it is not swallowed by the lifespan's group
      fault-isolation (`main.py`; the strategy-host group is `required = True` after
      `broker-sync-visibility`)
- [ ] 5.4 Log the satisfied input set on success

## 6. Vote breakdown logging
- [ ] 6.1 `backend/pdp/signals/bias.py:297-301`: `score_bias` returns per-input `(vote, weight, abstained)`
- [ ] 6.2 `directional_strangle.py:401`: emit the breakdown once per evaluation, alongside bucket + score
- [ ] 6.3 Confirm it lands in OpenSearch with queryable field names (not a single formatted string)

## 7. Re-baseline
- [ ] 7.1 Re-run the three strangle backtests with all eight inputs live
- [ ] 7.2 Compare the **bucket histogram** before/after, not just P&L — the expected effect is fewer
      `neutral` buckets
- [ ] 7.3 Record both histograms in this change's README and state whether the new baseline supersedes

## 8. Docs + validation
- [ ] 8.1 `backend/pdp/signals/CLAUDE.md` (create if absent): the eight inputs, their timeframe and
      family prerequisites, and the satisfiability rule
- [ ] 8.2 `docs/RUNBOOK.md`: `OPTIONS_UNDERLYINGS` must be set in `.env` on every target; how to verify
- [ ] 8.3 `task test` green against the recorded baseline
- [ ] 8.4 `openspec validate --strict bias-input-completeness` passes
