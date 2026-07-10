# Tasks — execution-console-accuracy

## 1. Levels warehouse — monthly period
- [x] 1.1 Add `compute_monthly()` to `LevelsStore` (mirror `compute_weekly`, `period="monthly"`)
- [x] 1.2 Add `_fetch_month_hlc()` and monthly compute in `compute_session_levels` (prior calendar month; recompute when missing)
- [x] 1.3 Extend `GET /api/v1/levels/{underlying}` `period` pattern to `daily|weekly|monthly`
- [x] 1.4 Verify `/api/v1/levels/NIFTY?period=monthly` returns populated camarilla + PMH/PML

## 2. Monitor matrix — read levels from the warehouse
- [x] 2.1 Replace `_build_pivot_cells` with async `_build_levels_cells(store, sid, session_date)` reading daily/weekly/monthly docs
- [x] 2.2 Emit `camarilla_daily/weekly/monthly` + `period{pdh,pdl,pwh,pwl,pmh,pml}`; null-safe on missing docs
- [x] 2.3 Resolve `session_date` (today IST) and build one `LevelsStore` per request in `strangle_monitor`

## 3. Warmup — 1D source + depth + params
- [x] 3.1 Add `_fetch_daily_from_dhan()` via `historical_daily_data`; stop short-circuiting `1D` to unsupported; persist bars
- [x] 3.2 Deepen `_TF_WARMUP_CALENDAR_DAYS` for 15m/1H/1D so EMA100 seeds ≥100 bars; recompute `target_bars`
- [x] 3.3 Pin SuperTrend(10,2) for the matrix index SIDs; confirm EMA[9,20,50,100,200] close + PSAR(0.02,0.02,0.2)
- [x] 3.4 Feed fetched 1D bars into weekly/monthly synth seeds

## 4. Matrix extra indicators + futures sourcing
- [x] 4.1 Add `ema200`, `rsi`, `rsi_ma`, `vwap`, `vwma` to `_build_indicator_cell`
- [x] 4.2 Configure suite: EMA(200), RSI(14, SMA signal 14) on spot SID; VWAP(hlc3, session) + VWMA(20) on futures SID
- [x] 4.3 Generalise futures-SID resolution per index; add futures SIDs to warmup + subscriptions
- [x] 4.4 Confirm/adjust RSI signal to SMA(14) to match Kite `RSI 14 SMA 14`

## 5. Events — 1D fires + (optional) detector re-source
- [x] 5.1 Confirm 1D `SUPERTREND_FLIP`/`EMA_CROSS`/`LEVEL_BREAK` fire once 1D bars seed (no new wiring)
- [x] 5.2 (Recommended) Re-source `LEVEL_BREAK`/`CAMARILLA_TOUCH` thresholds to `LevelsStore` so events match the matrix

## 6. Flutter — Live Events sidebar contract + promotion
- [x] 6.1 `live_events_source.dart`: drop `type=='event'` guard; gate on `event_type`/`id`
- [x] 6.2 `events_models.dart`: read `ts ?? timestamp`; normalise severity to lowercase
- [x] 6.3 `event_feed_sidebar.dart`: map `critical`/`error`→loss, `warning`→warning, else info
- [x] 6.4 Remove `_EventLog` heartbeat list from the Execution tab; ensure sidebar mounted alongside it

## 7. Flutter — matrix per-TF Camarilla + extra columns
- [x] 7.1 `_camForTf(tf)`: 5m/15m→daily, 30m/1H→weekly, 1D→monthly; add Cam R4/S4 to the grid
- [x] 7.2 Add EMA200/VWAP/VWMA/RSI columns; period pills per TF (PDH/PDL, PWH/PWL, PMH/PML)
- [x] 7.3 `execution_models.dart`: parse `camarilla_monthly`, `pmh/pml`, `ema200`, `vwap`, `vwma`, `rsi`, `rsi_ma`

## 8. Verify
- [x] 8.1 Levels vs Kite via `/api/v1/levels`; matrix via `/monitor` (PDH≠PDL≠price; 1D populated; ema100 non-null)
- [x] 8.2 Match NIFTY 50 spot baseline (ST/EMA/SAR/RSI per TF from Kite screenshots)
- [x] 8.3 `/ws/events` frame shape; sidebar appends live; severity colours; 1D event appears
- [x] 8.4 `cd app && flutter analyze && flutter test`; backend `task test`/`lint` for touched modules
- [x] 8.5 `openspec validate execution-console-accuracy --strict`; archive on green
