# Tasks — strangle-monitor-concurrent-fetch

## 0. Diagnostics (read-only, done)
- [x] 0.1 `/fastapi-code-review` (2026-07-17) identified 4 independent I/O chains in
      `strangle_monitor` awaited sequentially: indices (`routes.py:762-767`), per-leg Greeks
      (`:780-797`), indicator matrix cells (`:889-898`), ATM CE/PE rows (`:700-714`).

## 1. Concurrency fix
- [x] 1.1 Indices block: gather per-index `(spot_ltp, spot_age_s, future_ltp)` fetches across
      NIFTY/BANKNIFTY/SENSEX concurrently.
- [x] 1.2 Per-leg Greeks: gather `_get_greeks_for_strike` across all open non-hedge legs
      concurrently instead of one await per loop iteration.
- [x] 1.3 Indicator matrix: gather `_build_indicator_cell` across all `(sid, tf)` pairs
      concurrently.
- [x] 1.4 `_build_atm_option_rows`: gather the CE and PE resolve+build chains concurrently.

## 2. Tests
- [x] 2.1 `tests/strategy/test_monitor_route.py`: existing assertions on payload shape/values
      still pass unchanged (proves the refactor is behavior-preserving).
- [x] 2.2 `task test` full green, no regressions.

## 3. Verify + archive
- [x] 3.1 `openspec validate --strict strangle-monitor-concurrent-fetch`.
- [ ] 3.2 Live/boot smoke: confirm `/monitor` p50/p99 latency drops and `atm_option_rows_failed`
      timeout rate falls further on the next market day (already improved by the `option_bars`
      index fix this session; this is the compounding concurrency win on top of that).
- [ ] 3.3 `openspec archive strangle-monitor-concurrent-fetch`.
