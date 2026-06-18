## 1. Session-aware lookback

- [x] 1.1 In `src/pdp/indicators/warmup.py`, compute the most recent prior trading day by walking back from today over weekends + NSE holidays (reuse `pdp.options.gap_backfill.trading_days` / `holidays`); set the Mongo `since` to that day's session start (~03:45 UTC) instead of `now - LOOKBACK_HOURS`
- [x] 1.2 Raise the "Mongo sufficient?" threshold from `MIN_BARS = 10` to a prior-session-sized target so a thin Mongo triggers the Dhan fallback to fetch the full prior session
- [x] 1.3 Ensure the Dhan fallback range reaches the computed prior trading day (widen `_fetch_from_dhan`'s `from_date` if its hardcoded yesterday/today does not span weekends/holiday clusters)
- [x] 1.4 Leave `IndicatorEngine` unchanged (persistent tracker is already correct); confirm no reset is introduced

## 2. Tests

- [x] 2.1 Warmup across a weekend gap: `since` resolves to the prior *trading* session, not a fixed-hour window
- [x] 2.2 Mid-day-restart seed yields the carried-over direction (not a cold-start DOWN seed) given a prior up-session
- [x] 2.3 Prior session absent in Mongo → Dhan fallback is invoked (or documented cold-start when Dhan also unavailable)

## 3. Verification

- [x] 3.1 Start the paper process mid-session; `indicator_warmup_done` logs a direction matching the prior-session trend / chart, not a fresh DOWN seed
- [x] 3.2 Confirm parity: live SuperTrend direction at a given bar matches the backtest's warmed series for the same day
- [x] 3.3 `openspec validate --strict live-supertrend-session-warmup`
