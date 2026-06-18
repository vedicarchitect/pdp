## 1. Pre-implementation data verification

- [x] 1.1 Query MongoDB `option_bars` collection: `db.option_bars.findOne()` — check if `iv` field exists in documents
- [x] 1.2 Query MongoDB `expired_option_bars` collection: `db.expired_option_bars.findOne()` — check for `iv` field
- [x] 1.3 If IV field is absent, document the finding and add Black-Scholes inversion to the IV rank function (compute on the fly from premium/spot/strike/dte)

## 2. Backend OI buildup classification

- [x] 2.1 Add `classify_oi_buildup(current, previous)` function to `src/pdp/options/analytics.py` — classify each strike as long_buildup / short_buildup / short_covering / long_unwinding based on price Δ and OI Δ
- [x] 2.2 Add `GET /api/v1/options/{underlying}/oi-buildup` to `src/pdp/options/routes.py` — returns per-strike classification for current expiry; query param `expiry` (optional, defaults to current)
- [x] 2.3 Test: create `tests/options/test_oi_buildup.py` — test all 4 classification quadrants with mock data

## 3. Backend multi-strike OI series

- [x] 3.1 Add `multi_strike_oi_series(underlying, expiry, interval)` function to `analytics.py` — queries `option_chains` snapshots, returns OI change per strike over time
- [x] 3.2 Add `GET /api/v1/options/{underlying}/oi-series` to routes — query params: `expiry`, `interval` (5m, 15m, 1H, 1D), `strikes` (optional, default top 10 by OI)
- [x] 3.3 Test: mock chain snapshots, verify OI change computation

## 4. Backend straddle history

- [x] 4.1 Add `straddle_history(underlying, date)` function to `analytics.py` — query today's `option_chains` snapshots, compute ATM CE + PE premium at each timestamp
- [x] 4.2 Add `GET /api/v1/options/{underlying}/straddle-history` to routes — query param `date` (default today)
- [x] 4.3 Test: mock chain snapshots with known premiums, verify straddle sum

## 5. Backend IV rank and percentile

- [x] 5.1 Add `iv_rank_percentile(underlying, lookback_days=252)` function to `analytics.py` — query `option_bars` + `expired_option_bars` for historical ATM IV; compute rank and percentile
- [x] 5.2 Add `GET /api/v1/options/{underlying}/iv-history` to routes — returns `{current_iv, iv_rank, iv_percentile, iv_high, iv_low, lookback_days}`
- [x] 5.3 Test: mock IV history, verify rank and percentile calculations

## 6. Backend FII/DII interface

- [x] 6.1 Create `src/pdp/options/fii_dii.py` — define `FIIDIISource` protocol, `FIIDIIData` dataclass, and `StubFIIDIISource`
- [x] 6.2 Add `GET /api/v1/options/fii-dii` to routes — calls configured source's `fetch()`; returns `{"available": false}` when stub is active
- [x] 6.3 Wire `StubFIIDIISource` as default in `main.py` / dependency injection
- [x] 6.4 Test: verify stub returns `None`, endpoint returns `{"available": false}`

## 7. Frontend analytics panels

- [x] 7.1 Create `frontend/src/components/analytics/OIBuildupPanel.tsx` — DataTable with columns: Strike, Classification (color-coded Badge), Price Δ, OI Δ, OI Δ %
- [x] 7.2 Create `frontend/src/components/analytics/MultiStrikeOIChart.tsx` — recharts LineChart showing OI change over time for top strikes
- [x] 7.3 Create `frontend/src/components/analytics/StraddleHistoryChart.tsx` — recharts AreaChart showing ATM straddle premium over the day
- [x] 7.4 Create `frontend/src/components/analytics/IVRankGauge.tsx` — visual gauge (0–100) showing IV rank and percentile with current IV, 52-week high/low
- [x] 7.5 Create `frontend/src/components/analytics/FIIDIIPanel.tsx` — summary table of FII/DII net flows; conditionally rendered only when `available: true`

## 8. Frontend integration

- [x] 8.1 Update `frontend/src/routes/analytics.tsx` — add Tabs for the new panels alongside existing max-pain/GEX/PCR/OI panels
- [x] 8.2 Verify: navigate to `/analytics` — all tabs render, new panels fetch data correctly
- [x] 8.3 Verify: FII/DII panel is hidden when stub returns `available: false`

## 9. Final verification

- [x] 9.1 Run `pytest tests/options/ -v` — all pass
- [x] 9.2 Run `cd frontend && npm run build` — clean build
- [x] 9.3 Run `task lint` — no lint errors
- [x] 9.4 Visual check: all new analytics panels render with real or mock data
