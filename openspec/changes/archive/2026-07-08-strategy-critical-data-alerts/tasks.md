# Tasks — strategy-critical-data-alerts

## 1. Event vocabulary + reusable emit path
- [x] 1.1 Add `WARMUP_INCOMPLETE`, `MISSING_LTP`, `NAKED_POSITION`, `FEED_STALE`,
      `INDICATOR_UNSEEDED`, `EXCEPTION_CRITICAL` to `events/models.py` `EventType`
- [x] 1.2 Add `EventService.emit_critical(...)` routing through the existing `emit` dedup gate
- [x] 1.3 Add `StrategyContext.emit_critical(...)` passthrough (no direct `Event` construction in strategies)

## 2. Missing-data guards
- [x] 2.1 Naked-hedge guard in `directional_strangle._open_hedge`/`_open_momentum`: bounded
      wait-for-tick, else square short + `NAKED_POSITION` (C5)
- [x] 2.2 Unseeded-ORB guard: detect non-open seeding, `INDICATOR_UNSEEDED`, exclude ORB vote (C9)
- [x] 2.3 Disarm-until-warm in `strategy/host.py` + `indicators/warmup.py`: `WARMUP_INCOMPLETE`
- [x] 2.4 Wire `FeedWatchdog`/`FeedStaleHalt` → `FEED_STALE`

## 3. VIX gate correctness (C13)
- [x] 3.1 Feed the gate 5m VIX candle values + 09:15 day-open baseline (parity with backtest)

## 4. Exception hardening
- [x] 4.1 Replace money/data-path `except Exception: log.warning` swallows with re-raise or
      `EXCEPTION_CRITICAL`; keep broad excepts only in boundaries/teardown

## 5. Flutter
- [x] 5.1 Add the six new types to the Dart event enum + CRITICAL icon/style in `app/lib/features/events/`

## 6. Tests + validation
- [x] 6.1 Backend tests per Phase 3 (emit fan-out+dedup, naked-hedge, ORB, warmup, feed-stale, VIX)
- [x] 6.2 Flutter widget test for a `NAKED_POSITION` CRITICAL event
      (`app/test/critical_alerts_card_test.dart`, added 2026-07-09 verification pass)
- [x] 6.3 `task test` + `cd app && flutter analyze && flutter test` green
      (NOTE: 2026-07-09 verification found this was NOT green as archived — the FEED_STALE
      event emit (2.4) was missing, and two tests broke on the new guards:
      `test_close_unpriced_emits_critical_and_aborts` (fake ctx lacked `emit_critical`) and
      `test_supertrend_smoke::test_pipeline_signal_to_journal` (warmup-disarm guard). All fixed.)
- [x] 6.4 `openspec validate --strict strategy-critical-data-alerts` passes
