# Tasks — bar-session-anchoring

## 1. Tests first (they fail on today's code)
- [ ] 1.1 `tests/market/test_bar_boundary.py`: parametrise over `[5m, 15m, 25m, 30m, 1H]` × four
      consecutive trading days; assert the bucket of the 09:15:00 IST tick starts at 09:15 IST
- [ ] 1.2 Assert 5m/15m boundaries are byte-identical to the current epoch-anchored output (no regression)
- [ ] 1.3 Assert 1D/1w boundaries are unchanged
- [ ] 1.4 Session-window: ticks at 09:14:59 and 15:30:00 produce no bar; 09:15:00 and 15:29:59 do
- [ ] 1.5 Session-end flush emits the 15:00–15:30 bar at 15:30 with no further tick
- [ ] 1.6 A Monday following a Friday holiday anchors on the Monday session open

## 2. Anchoring
- [ ] 2.1 `bars.py`: add `_session_open_utc(dt) -> datetime` (09:15 IST on the tick's IST trading day)
- [ ] 2.2 `_bar_boundary(dt, tf_minutes)` truncates `(dt - session_open)` into `tf_minutes` buckets
- [ ] 2.3 Leave `_bar_boundary_1d` and `_bar_boundary_1w` untouched
- [ ] 2.4 Confirm no other module reimplements bucket maths (`grep -rn "// tf_minutes\|// 60" backend/pdp`)

## 3. Session window
- [ ] 3.1 `BarAggregator.on_tick`: drop ticks outside `[09:15:00, 15:30:00)` IST
- [ ] 3.2 Use the existing trading-calendar helper so holidays are handled, not a weekday check
- [ ] 3.3 Add `flush_session()` to close the final bucket; call it from the session-end scheduler
- [ ] 3.4 Verify the hot path stays allocation-light — the window check must be an integer compare,
      not a `ZoneInfo` conversion per tick (precompute the day's UTC window bounds once)

## 4. Rebuild stored bars
- [ ] 4.1 `mongodump` `market_bars` before anything else; record the archive path in the change log
- [ ] 4.2 `backend/scripts/oneoff/rebuild_market_bars.py`: read 1m for `(sid, date-range)`, aggregate
      to 15m/30m/1H (and 25m if configured), delete-then-insert per `(sid, tf)`
- [ ] 4.3 Reuse `BarAggregator`'s bucket function — do not reimplement it in the script
- [ ] 4.4 `--dry-run` prints per-`(sid, tf)` before/after document counts and the first/last `ts`
- [ ] 4.5 Idempotence test: run twice, assert identical document sets
- [ ] 4.6 Equivalence test: replay one session's 1m bars through `BarAggregator`; assert the script's
      30m output matches
- [ ] 4.7 Run for all `WAREHOUSE_UNDERLYINGS`; assert the 1m document count is unchanged afterwards

## 5. Verify against the broker
- [ ] 5.1 Pull Kite (or Dhan) 30m candles for NIFTY for five recent sessions
- [ ] 5.2 Bar-by-bar OHLC comparison against rebuilt `market_bars`; document any residual delta
- [ ] 5.3 Recompute 30m EMA(20/50) from rebuilt bars; compare against the Kite matrix values that
      motivated this change (24017 / 24063 / 24158)

## 6. Re-baseline the backtests
- [ ] 6.1 Re-run the three strangle configs after the rebuild
- [ ] 6.2 Record new net P&L / PF / MaxDD alongside the archived baselines in this change's README
- [ ] 6.3 Explicitly decide (and write down) whether the new numbers supersede the archived ones

## 7. Docs + validation
- [ ] 7.1 `backend/pdp/market/CLAUDE.md`: document session anchoring and the session window; fix the
      stale `market_bars` schema (it is a timeseries keyed on `metadata.security_id` / `metadata.timeframe`)
- [ ] 7.2 `docs/RUNBOOK.md`: how to re-run the rebuild and how to restore from the dump
- [ ] 7.3 `task test` green against the recorded baseline
- [ ] 7.4 `openspec validate --strict bar-session-anchoring` passes
