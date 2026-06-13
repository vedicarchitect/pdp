## Why

The `options-analytics` capability already polls chains, computes max-pain and PCR, and stores snapshots in MongoDB — but there is no frontend to surface any of it, and GEX is entirely absent. Traders watching NIFTY options need three real-time signals that require zero additional data collection: Max Pain (where the market "wants" to pin), GEX (where dealers are hedging and creating invisible support/resistance), and PCR/OI heatmap (conviction and positioning across strikes). All three are computable from the existing `option_chains` collection the poller already fills.

## What Changes

- New `compute_gex()` function in `src/pdp/options/analytics.py` — net GEX per strike and aggregate GEX.
- New `GET /api/v1/options/{underlying}/gex` REST endpoint in `src/pdp/options/routes.py`.
- New `GET /api/v1/options/{underlying}/oi-history` REST endpoint — returns PCR time-series and per-strike OI from the last N snapshots (for OI heatmap data).
- New `/analytics` frontend route with three panels:
  - **MaxPainChart** — bar chart of writer pain by strike, vertical marker at the max-pain strike.
  - **GEXChart** — signed bar chart of net GEX by strike (green = long gamma / dealer buys on dip, red = short gamma / dealer sells on dip); aggregate net GEX badge.
  - **OIHeatmap** — strike × time heatmap of total OI; PCR time-series overlay.
- Navigation link to `/analytics` added to the Sidebar.

## Capabilities

### New Capabilities
- `options-analytics-tools`: Frontend analytics page with Max Pain, GEX, and OI heatmap panels powered by the existing MongoDB options chain snapshots.

### Modified Capabilities
- `options-analytics`: Two new REST endpoints added (`/gex`, `/oi-history`); GEX computation added to `analytics.py`. Existing chain/max-pain/pcr endpoints and MongoDB schema unchanged.

## Impact

- `src/pdp/options/analytics.py` — add `compute_gex(strikes, lot_size, spot) -> dict`.
- `src/pdp/options/routes.py` — add two new `@router.get` handlers.
- `frontend/src/routes/analytics.tsx` — new route file.
- `frontend/src/components/analytics/MaxPainChart.tsx` — new component.
- `frontend/src/components/analytics/GEXChart.tsx` — new component.
- `frontend/src/components/analytics/OIHeatmap.tsx` — new component.
- `frontend/src/components/Sidebar.tsx` — add Analytics nav link.
- `frontend/src/routes/__root.tsx` — register `/analytics` route.
- No database schema changes; no new dependencies (charts use existing Recharts/lightweight-charts already in the frontend).
- Tests: `tests/options/test_analytics.py` — unit tests for `compute_gex`.
