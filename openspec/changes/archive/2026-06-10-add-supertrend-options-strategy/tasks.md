## 1. Universal SuperTrend indicator

- [x] 1.1 `pdp/indicators/supertrend.py` — `SuperTrendTracker` (Wilder ATR, O(1)) + `supertrend()` batch helper + `SuperTrendState`
- [x] 1.2 `pdp/indicators/engine.py` — `IndicatorEngine` (one tracker per (sid, tf), `on_bar`, `get`)
- [x] 1.3 Wire `IndicatorEngine` into `TickRouter` before strategy dispatch; cache latest to Redis `st:<sid>:<tf>`
- [x] 1.4 Unit tests: ATR seeding, uptrend/downtrend direction, flip detection

## 2. Strike resolution

- [x] 2.1 `pdp/strategy/strikes.py` — `nearest_weekly_expiry`, `resolve_otm_option`
- [x] 2.2 Unit tests: ATM rounding, OTM shift for CE/PE

## 3. Strategy host context

- [x] 3.1 Extend `StrategyContext` with `indicators`, `market`, `session_maker`
- [x] 3.2 `IndicatorReader` + `MarketControl` wrappers; `StrategyHost` setters; thread into context

## 4. SuperTrend short strategy

- [x] 4.1 `pdp/strategies/supertrend_short.py` — open/scale-in/flip/square-off logic
- [x] 4.2 `strategies/supertrend_short.yaml` — NIFTY 5m watchlist, params, schedule, risk
- [x] 4.3 Unit tests: open on signal, scale-in cap, flip close+reverse, square-off, before-window gate

## 5. Paper journal

- [x] 5.1 `pdp/journal/stats.py` — pure `compute_daily_stats`
- [x] 5.2 `pdp/journal/service.py` — `JournalService` (fill callback, buffer, Mongo flush)
- [x] 5.3 `pdp/journal/routes.py` — `GET /api/v1/journal`, `GET /api/v1/journal/stats`
- [x] 5.4 Unit tests for `compute_daily_stats`

## 6. Wiring

- [x] 6.1 `main.py` — create `IndicatorEngine`, set on host + TickRouter; set market adapter on host
- [x] 6.2 `main.py` — create + start `JournalService`, register fill callback, register router

## 7. Frontend

- [x] 7.1 `frontend/src/routes/strategies.tsx` — start/stop controls + journal P&L/stats panel

## 8. Validation

- [x] 8.1 `pytest` green for new unit tests (18 passing; 120 across affected suites)
- [x] 8.2 Backtest replay on a historical NIFTY 5m day (`backtest_multiday.py`, multi-day runs Jun 2026)
- [x] 8.3 Paper smoke test with synthetic bars: signal -> strategy -> order -> fill -> journal
  (`tests/strategy/test_supertrend_smoke.py`)
- [x] 8.4 Archive change via `openspec archive add-supertrend-options-strategy`

## Blockers (pre-existing, outside this change) — RESOLVED

- [x] B.1 `pdp/alerts/evaluator.py` `load_alerts` crashed app startup when the live-feed branch
  runs (the `.env` has live Dhan creds). Fixed: `main.py` now passes the sessionmaker instance
  (`get_session_maker()`), and `load_alerts` tolerates a missing `alerts` table (catches
  `ProgrammingError`, mirroring `PaperBroker`). App lifespan tests now pass.
