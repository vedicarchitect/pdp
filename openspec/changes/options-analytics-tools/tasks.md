## 1. Backend — GEX computation

- [ ] 1.1 Add `compute_gex(strikes: list[dict], lot_size: int, spot: float) -> dict` to `src/pdp/options/analytics.py` — returns `{"per_strike": [{"strike": int, "gex": float}], "net_gex": float}`
- [ ] 1.2 Handle missing `gamma` fields in CE/PE dicts (default to 0, no KeyError)
- [ ] 1.3 Add `tests/options/test_analytics.py` with unit tests: single-strike GEX calculation, missing gamma defaults, net GEX sum, empty strikes list

## 2. Backend — new REST endpoints

- [ ] 2.1 Add `GET /{underlying}/gex` route to `src/pdp/options/routes.py` — reads latest snapshot, calls `compute_gex`, returns `per_strike`, `net_gex`, `net_gex_cr` (= `net_gex / 1e9` rounded to 2dp), paper-mode guard
- [ ] 2.2 Add `GET /{underlying}/oi-history` route — queries `option_chains` collection for last `n` (default 40, max 200) snapshots by `(underlying, expiry)` sorted ascending by `snapshot_ts`; returns `snapshots` array with `ts`, `pcr`, and per-strike `ce_oi`/`pe_oi`/`total_oi`; paper-mode guard
- [ ] 2.3 Run `pytest tests/options/test_analytics.py -v` — all pass
- [ ] 2.4 Run `pyright src/pdp/options/analytics.py src/pdp/options/routes.py` — no errors

## 3. Frontend — dependency and routing

- [ ] 3.1 Add `recharts` to `frontend/package.json` via `npm install recharts` in the `frontend/` directory
- [ ] 3.2 Create `frontend/src/routes/analytics.tsx` — route component that renders the analytics page layout with underlying selector, expiry selector, and three panel placeholders
- [ ] 3.3 Register `/analytics` route in `frontend/src/routes/__root.tsx`
- [ ] 3.4 Add "Analytics" nav link to `frontend/src/components/Sidebar.tsx` (icon: `BarChart2` from lucide-react)

## 4. Frontend — MaxPainChart component

- [ ] 4.1 Create `frontend/src/components/analytics/MaxPainChart.tsx` — fetches `GET /api/v1/options/{underlying}/chain?expiry=...` via TanStack Query with `refetchInterval: 30_000`
- [ ] 4.2 Render Recharts `BarChart` with pain-per-strike bars, `ReferenceLine` at `max_pain` (amber), `ReferenceLine` at `spot_price` (blue), x-axis = strike, y-axis = pain value
- [ ] 4.3 Show paper-mode placeholder when `response.mode === "paper"`
- [ ] 4.4 Show loading skeleton while data fetches

## 5. Frontend — GEXChart component

- [ ] 5.1 Create `frontend/src/components/analytics/GEXChart.tsx` — fetches `GET /api/v1/options/{underlying}/gex?expiry=...` via TanStack Query with `refetchInterval: 30_000`
- [ ] 5.2 Render Recharts `BarChart` with `Cell` fill: green if `gex >= 0`, red if `gex < 0`; x-axis = strike, y-axis = GEX value
- [ ] 5.3 Display net GEX badge above chart: `"Net GEX: +₹3.42 Cr"` (sign-aware, green/red colour)
- [ ] 5.4 Show paper-mode placeholder when `response.mode === "paper"`

## 6. Frontend — OIHeatmap component

- [ ] 6.1 Create `frontend/src/components/analytics/OIHeatmap.tsx` — fetches `GET /api/v1/options/{underlying}/oi-history?expiry=...&n=40` via TanStack Query with `refetchInterval: 30_000`
- [ ] 6.2 Render CSS grid heatmap: rows = strikes (sorted descending), columns = snapshots (time-ascending); cell background opacity = `total_oi / column_max_oi`; cell tooltip shows absolute OI on hover
- [ ] 6.3 Render Recharts `LineChart` below heatmap for PCR over time, shared time axis with heatmap columns
- [ ] 6.4 Show paper-mode placeholder when `response.mode === "paper"`

## 7. Integration verification

- [ ] 7.1 Start dev server (`npm run dev` in `frontend/`) and navigate to `/analytics` — page loads without console errors
- [ ] 7.2 Verify paper-mode placeholder renders in all three panels (default state without live credentials)
- [ ] 7.3 Verify underlying selector switches all three panels simultaneously
- [ ] 7.4 Verify Sidebar "Analytics" link navigates to `/analytics`
