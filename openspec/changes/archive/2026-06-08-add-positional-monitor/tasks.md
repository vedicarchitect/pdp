## 1. Backend — Positional Module Scaffold

- [x] 1.1 Create `src/pdp/positional/` package with `__init__.py`, `models.py`, `routes.py`
- [x] 1.2 Define `PositionalSnapshotDocument` Pydantic model (date, total_unrealized_pnl, total_realized_pnl, day_pnl, position_count, created_at, mode)
- [x] 1.3 Add `positional_eod_snapshots` collection accessor to `src/pdp/mongo/collections.py`
- [x] 1.4 Mount positional router in `src/pdp/main.py` under `/api/v1/positional`

## 2. Backend — EOD Snapshot Endpoints

- [x] 2.1 Implement `POST /api/v1/positional/snapshot` — upsert snapshot into MongoDB keyed on `date`, return 201 with the document
- [x] 2.2 Implement `GET /api/v1/positional/snapshots?days=N` — query last N documents sorted by date ascending, return 200 with array
- [x] 2.3 Add paper-mode guard: include `"mode": "paper"` in snapshot when `LIVE=0`
- [x] 2.4 Write unit tests for both endpoints (mock MongoDB client)

## 3. Frontend — React Hooks

- [x] 3.1 Create `src/hooks/usePositionalFeeds.ts` — subscribe to `/ws/portfolio`, group positions by `strategy_id`, expose `groups` and `connectionState`
- [x] 3.2 Create `src/hooks/useOptionsGreeks.ts` — fetch latest snapshot via `GET /api/v1/options/{underlying}/chain`, return per-strike Greek map with `lastUpdated` timestamp
- [x] 3.3 Create `src/hooks/useEodHistory.ts` — fetch `GET /api/v1/positional/snapshots` on mount, return sorted `DayPnL[]` array
- [x] 3.4 Expose new hooks from `src/hooks/index.ts`

## 4. Frontend — Positional Components

- [x] 4.1 Create `src/types/positional.ts` — `StrategyGroup`, `PositionalLeg`, `DayPnL`, `RolloverEstimate` types
- [x] 4.2 Create `src/components/positional/StrategyGroupRow.tsx` — collapsible row showing aggregate Δ, Γ, Θ, V, P&L with expand/collapse for legs
- [x] 4.3 Create `src/components/positional/LegRow.tsx` — individual leg: symbol, expiry, qty, avg_price, ltp, per-leg P&L, per-leg Greeks, stale indicator
- [x] 4.4 Create `src/components/positional/ExpiryAlertPanel.tsx` — renders T-7/T-3/T-1 alert pills for all legs with DTE ≤ 7
- [x] 4.5 Create `src/components/positional/RolloverPanel.tsx` — fetches chain on demand, computes rollover cost, shows slippage input
- [x] 4.6 Create `src/components/positional/PnLSparkline.tsx` — line chart (recharts or similar) of `day_pnl` over time; green/red coloring; placeholder when empty
- [x] 4.7 Create `src/components/positional/PositionalPage.tsx` — assembles all components; wires hooks; handles loading/empty states

## 5. Frontend — Route Wire-Up

- [x] 5.1 Replace stub in `src/routes/positional.tsx` with import of `PositionalPage` component
- [x] 5.2 Verify the `/positional` sidebar link in `src/components/Sidebar.tsx` is active and navigates correctly

## 6. Greek Enrichment & Staleness

- [x] 6.1 In `useOptionsGreeks`, compare `snapshot.created_at` to `Date.now()` and set `isStale = age > 60_000`
- [x] 6.2 In `LegRow`, show a stale badge and `last_updated` tooltip when `isStale` is true for that underlying
- [x] 6.3 When no snapshot exists for a leg's underlying, render `—` in Greek cells with no stale badge

## 7. Expiry DTE Computation

- [x] 7.1 Add `computeDTE(expiryDate: string): number` utility to `src/lib/utils.ts`
- [x] 7.2 In `ExpiryAlertPanel`, filter legs to DTE ≤ 7 and render appropriate alert pill severity (amber / orange / red)
- [x] 7.3 Add unit test for `computeDTE` covering same-day (DTE=0), DTE=1, DTE=7, DTE=8

## 8. Rollover Estimator

- [x] 8.1 In `RolloverPanel`, on "Estimate Rollover" click: call `GET /api/v1/options/{underlying}/chain`, find matching strike in the next expiry, compute `rollover_cost`
- [x] 8.2 Render `current_mid`, `next_mid`, `rollover_cost`, and a slippage input (default 0.1%)
- [x] 8.3 Recompute `slippage_estimate` reactively on slippage input change without re-fetching
- [x] 8.4 Show "No next expiry available" when only one expiry exists in the chain response

## 9. Tests

- [x] 9.1 Add `src/test/positionalAggregation.test.ts` — Greek aggregation logic across multi-leg groups
- [x] 9.2 Add `src/test/expiryAlerts.test.ts` — alert severity rules for T-7 / T-3 / T-1
- [x] 9.3 Add `src/test/rolloverEstimator.test.ts` — rollover cost and slippage calculation
- [x] 9.4 Run full frontend test suite (`vitest run`) and fix any regressions
