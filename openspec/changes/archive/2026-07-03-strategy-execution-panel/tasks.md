## 1. Options poller default-on (paper realtime)
- [x] 1.1 `pdp/main.py:343` — change gate to `if settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN:` (drop `settings.LIVE`)
- [x] 1.2 Add `OPTIONS_POLLER_ENABLED: bool = True` to `pdp/settings.py`; honour it in the start gate
- [x] 1.3 Update `pdp/options/CLAUDE.md` "Start Condition" + RUNBOOK note

## 2. OpenLeg entry metadata
- [x] 2.1 `directional_strangle.py` `OpenLeg` (~L93) — add `entry_time: datetime | None = None`, `entry_reason: str = ""`
- [x] 2.2 Populate at the 3 construction sites (short ~L689, hedge ~L751, momentum ~L806): `datetime.now(tz=_IST)` + reason `f"{self._current_bucket}@{self._last_score:.2f}"`
- [x] 2.3 Add `entry_time`/`entry_reason` to each leg dict in `state()` (~L975)

## 3. Weekly (1w) bars + weekly Camarilla
- [x] 3.1 `pdp/market/bars.py` `BarAggregator` — add `"1w"` timeframe with ISO-week boundary rollup
- [x] 3.2 Ensure `BarWriter` persists `1w` bars to `market_bars`
- [x] 3.3 `pdp/indicators/engine.py` + `warmup.py` — seed/compute `1w` pivots so `get_pivots(sid,"1w")` returns cam fields
- [x] 3.4 `directional_strangle.py:589-594` — drop the `cam_weekly_missing` guard once `1w` returns data
- [x] 3.5 Unit test: ISO-week boundary rollup + weekly Camarilla values

## 4. Monitor endpoint
- [x] 4.1 `GET /api/v1/strangle/monitor` in `pdp/strategy/routes.py` — indices spot+future LTP (Redis `ltp:`)
- [x] 4.2 Legs grouped by underlying with entry_time/reason, ltp, mtm
- [x] 4.3 Per active non-hedge strike: Greeks/OI/PCR from latest `option_chains` snapshot + OI-change-since-day-start
- [x] 4.4 Totals (per-index + overall), status, recent_events from `_activity`
- [x] 4.5 Indicator matrix (EMA/ST/PSAR × 5m/15m/30m/1H/1D) + daily/weekly Camarilla + PDH/PDL/PWH/PWL
- [x] 4.6 Unit test: payload shape + 404 when strangle not running

## 5. Levels warehouse (Mongo `index_levels`)
- [x] 5.1 `pdp/mongo/` collection init — `index_levels` + indexes (unique `(security_id,period,session_date)`)
- [x] 5.2 `pdp/indicators/levels_store.py` `LevelsStore` — reuse `pivots._compute_pivots`; `upsert/get/range/to_feature_rows/compute_daily/compute_weekly`
- [x] 5.3 Daily compute task (lifespan/`pdp/jobs`) for 3 indices from prior trade day; weekly each Monday; idempotent
- [x] 5.4 `scripts/backfill_levels.py` (model on `backfill_spot.py`) — 5yr daily+weekly; `--symbol --from --to --only-missing --dry-run`
- [x] 5.5 Wire `task backfill:levels` in root `Taskfile.yml` + `scripts/CLAUDE.md`
- [x] 5.6 `GET /api/v1/levels/{underlying}?period=&date=` (+ range)
- [x] 5.7 Unit test: daily→weekly rollup + ISO-week boundary; note `index_levels` as ML feature source in `pdp/ml/`
- [x] 5.8 Backfill run for NIFTY(13)/BANKNIFTY(25)/SENSEX(51)

## 6. Flutter Strategy Execution tab
- [x] 6.1 `manage_hub_screen.dart` — add 5th tab (`length:4→5`, `Tab` + `StrategyExecutionTab()`)
- [x] 6.2 `domain/execution_models.dart` — MonitorSnapshot/IndexQuote/LegRow/IndicatorCell/Totals (hand-written fromJson + `_asDouble`)
- [x] 6.3 `data/execution_source.dart` + `live_execution_source.dart` — REST poll ~2s; cancel timer in `onCancel` before `yield*`
- [x] 6.4 `application/manage_providers.dart` — `executionSourceProvider` + `executionStreamProvider`
- [x] 6.5 `presentation/tabs/strategy_execution_tab.dart` — index bar, grouped positions DataTable, totals/status, indicator matrix; `AppColors.*`
- [x] 6.6 `flutter analyze && flutter test`

## 7. Validate
- [x] 7.1 `task openspec:validate -- strategy-execution-panel --strict` clean
- [x] 7.2 Backend `task test lint typecheck`; owner paper-run confirms panel end-to-end before archive
