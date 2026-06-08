## Context

The platform already supports intraday position monitoring (`/intraday`) with live P&L, Greek aggregation, and kill-switch risk controls. Swing / F&O positional traders need a separate surface with a longer time horizon: multi-expiry Greek aggregation across a book held overnight, expiry-awareness with rolling cost estimation, and daily EOD P&L snapshots for curve tracking.

The existing `portfolio` module exposes `GET /api/v1/portfolio/positions` and `/ws/portfolio`. The `options-analytics` module persists per-expiry Greek snapshots to MongoDB. Both are consumed by the intraday monitor. The positional monitor reuses these feeds but adds:

- **Expiry lifecycle** — T-7 / T-3 / T-1 alert events, rollover cost estimate.
- **Multi-leg aggregation** — group positions by `strategy_id`, sum Δ, Γ, Θ, V.
- **EOD snapshot** — one P&L record per trading day stored in MongoDB for charting.

Stakeholders: solo swing trader running multi-leg F&O strategies (Iron Condors, Calendar Spreads).

---

## Goals / Non-Goals

**Goals:**
- `/positional` SPA page: leg-grouped strategy view with aggregate Greeks and net P&L.
- Expiry alerts (T-7, T-3, T-1) surfaced via banner and a dedicated alert panel.
- Rollover cost helper comparing current vs. next-expiry mid + slippage estimate.
- EOD P&L snapshot stored once per day at market close; exposed via REST for sparkline chart.
- Reuse existing `/ws/portfolio` and `options-analytics` data — no new polling loops.

**Non-Goals:**
- Live intraday kill-switch / per-strategy hard cap (covered by intraday-monitor).
- Backtesting or historical simulation of positional strategies.
- Cross-broker support (Dhan only for now).
- Sending rollover orders automatically.

---

## Decisions

### D1 — Reuse `/ws/portfolio` for position feed
The intraday monitor already consumes this feed. The positional page adds a React hook `usePositionalFeeds` that subscribes to the same WebSocket but groups by `strategy_id` and enriches each leg with Greeks from the latest options snapshot.

**Alternatives considered:** A dedicated `/ws/positional` endpoint — rejected; adds a new broadcast path without new data. Polling REST — rejected; 50 ms latency requirement from platform-core applies.

### D2 — Greek aggregation in the frontend
The positional page aggregates Greeks per strategy group in JavaScript (sum of `delta * net_qty`, etc.) rather than adding a server-side aggregation endpoint. The options-analytics module already persists per-strike Greeks; the frontend joins on `security_id`.

**Alternatives considered:** A `/api/v1/positional/book` endpoint that returns pre-aggregated Greeks — deferred; adds backend complexity with no latency benefit for a low-frequency positional view.

### D3 — Expiry alerts derived client-side from position data
Each position row carries `expiry_date` (sourced from the instrument registry). The frontend computes `days_to_expiry = expiry_date − today()` on render and fires alert state when DTE ≤ 7 / 3 / 1. No server-side event bus needed.

**Alternatives considered:** Server-push alert events via WebSocket — overkill; the positional page is opened at most a few times a day by the trader and a render-time check is sufficient.

### D4 — Rollover cost from options-analytics REST
`GET /api/v1/options/{underlying}/chain` already returns strike-level mid prices for all available expiries. The rollover panel calls this endpoint on demand (user clicks "Estimate Rollover") for the relevant underlying, finds the next-expiry equivalent strike, and computes `rollover_cost = next_expiry_mid − current_expiry_mid + slippage`.

### D5 — EOD snapshot via a new backend route + MongoDB collection
A new `POST /api/v1/positional/snapshot` endpoint writes a single document to a `positional_eod_snapshots` collection at market close (called by a scheduled job or manually). `GET /api/v1/positional/snapshots` returns the last 90 days for the sparkline chart.

**Alternatives considered:** Storing in PostgreSQL — possible, but MongoDB already holds options snapshots and adding one more collection is cheaper than a new PG table migration.

---

## Risks / Trade-offs

- **Greek staleness** — options snapshots are polled every 30 s. Greeks shown in the positional view can be up to 30 s stale. Mitigation: show a `last_updated` timestamp and flag `greeks_stale` when snapshot age > 60 s.
- **Missing `strategy_id` on positions** — positions placed without a `strategy_id` fall into an "Untagged" group. Mitigation: UI renders an "Untagged" row; documentation asks traders to always pass `strategy_id` on orders.
- **Rollover cost accuracy** — mid = (bid + ask) / 2 from the snapshot, not live order book. Actual fill will differ. Mitigation: UI labels the estimate "indicative" and adds a slippage buffer input.
- **EOD snapshot missed** — if the process is down at 15:35, the day's snapshot is skipped. Mitigation: expose the `POST /api/v1/positional/snapshot` endpoint so the trader can trigger it manually; log a warning at 15:30.

---

## Migration Plan

1. Add `positional_eod_snapshots` MongoDB collection (no schema migration; MongoDB is schemaless).
2. Add backend routes (`/api/v1/positional/*`) under a new `src/pdp/positional/` module, mounted in `main.py`.
3. Build frontend components under `src/components/positional/` following the intraday component pattern.
4. Wire `frontend/src/routes/positional.tsx` (stub already exists) to the new page component.
5. Rollback: remove the new routes from `main.py`; the stub route reverts to the placeholder heading.

---

## Open Questions

- Should `expiry_date` be stored on the `positions` PG table, or should the frontend resolve it from the instrument registry API? (Currently not on `positions`.)
- What slippage buffer default should the rollover estimator show? (Suggest 0.1% as a starting point.)
- Should the EOD snapshot trigger be a cron inside the app or an external scheduler call?
