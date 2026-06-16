## Context

The `option_chains` MongoDB collection is already populated by the options poller with per-expiry snapshot documents containing `strikes` (array of `{strike, ce: {oi, iv, delta, gamma, …}, pe: {oi, …}}`), `max_pain`, `pcr`, `spot_price`, and `snapshot_ts`. The `analytics.py` module already implements `compute_max_pain()` and `compute_pcr()`. The REST layer in `routes.py` exposes `/chain`, `/max-pain`, `/pcr`, and `/refresh`.

The frontend currently has `lightweight-charts` for time-series but no bar/histogram charting library. The analytics panels (Max Pain, GEX) are categorical bar charts (strike on x-axis, value on y-axis), not time-series, so `lightweight-charts` is not the right fit for them.

## Goals / Non-Goals

**Goals:**
- Add `compute_gex()` to `analytics.py` and a `/gex` REST endpoint.
- Add an `/oi-history` REST endpoint for PCR time-series and OI heatmap data.
- Build a `/analytics` frontend page with three panels.
- Keep all frontend charts functional in paper mode (show empty/placeholder state gracefully).

**Non-Goals:**
- Real-time WebSocket push to the analytics page (polling on a 30s interval is sufficient).
- GEX persistence in MongoDB (compute on-the-fly from snapshot data).
- Multi-underlying analytics on one page (single underlying selector, NIFTY default).

## Decisions

### D1: Add `recharts` for bar and line charts

`lightweight-charts` is optimised for financial time-series (candlesticks, lines on a time axis). The Max Pain chart (pain value per strike) and GEX chart (GEX per strike) are categorical bar charts. Implementing these as SVG manually is verbose and harder to maintain.

`recharts` is the standard React bar/line chart library (MIT, ~120KB gzipped, no transitive deps beyond React). It handles: `BarChart` with `ReferenceLine` (max pain marker), signed bars via `Cell` fill colours (GEX positive/negative), and `LineChart` for PCR over time.

**Decision:** Add `recharts` as a frontend dependency.

**Alternative considered:** Custom SVG bars using Tailwind/divs. Rejected — no tooltip, no axis labels, brittle for variable strike counts.

### D2: OI heatmap as CSS grid, not a third-party heatmap library

A proper 2D heatmap (strike × time) can be rendered as a `<div>` CSS grid where each cell's background-colour is interpolated between `transparent` and a base colour (e.g., amber) using the OI value normalised to the column max. This requires no additional library and keeps bundle size down.

The `/oi-history` endpoint returns a matrix: `{ snapshots: [{ts, pcr, strikes: [{strike, ce_oi, pe_oi, total_oi}]}] }`. The frontend maps this into a grid.

### D3: GEX formula

GEX per strike (net dealer gamma exposure):

```
GEX(K) = (CE_gamma(K) × CE_OI(K) - PE_gamma(K) × PE_OI(K)) × lot_size × spot²
```

Positive GEX → dealers long gamma → stabilising (buy dips, sell rallies).  
Negative GEX → dealers short gamma → destabilising (sell dips, buy rallies).

`lot_size` and `spot` are passed in by the route handler from the snapshot document (`spot_price`) and `settings.LOT_SIZES[underlying]` (already used in the poller).

Net aggregate GEX = sum of GEX(K) across all strikes, divided by 10^9 for display (₹ crore equivalent).

### D4: `/oi-history` endpoint — last N snapshots

Query the `option_chains` collection for the last N documents matching `(underlying, expiry)` sorted by `snapshot_ts` descending, then reverse for time-ascending display. Default N=40 (≈20 minutes at 30s poll interval). The response shape:

```json
{
  "underlying": "NIFTY",
  "expiry": "2026-06-26",
  "snapshots": [
    {"ts": "...", "pcr": 1.12, "strikes": [{"strike": 22400, "ce_oi": 1200000, "pe_oi": 800000}]},
    ...
  ]
}
```

### D5: Analytics page polling, not WebSocket

The analytics page polls each endpoint every 30 seconds via TanStack Query (`refetchInterval: 30_000`). This matches the poller interval and avoids WebSocket subscription management complexity for a read-only analytics view.

### D6: Paper mode graceful empty state

When the poller is not active (paper mode / no credentials), all three backend endpoints return `{"mode": "paper", ...}`. The frontend detects `mode === "paper"` and renders a `PaperModePlaceholder` panel with a lock icon and "Live data requires LIVE=1 and Dhan credentials" message.

## Risks / Trade-offs

- [GEX gamma quality] Gamma values come from Dhan's option chain or fallback vollib computation. Low-precision gamma (e.g., 0.00 for deep OTM) will make GEX look flat. → Acceptable for now; GEX is most meaningful near ATM where gamma is highest.
- [recharts bundle size] Adds ~120KB to the frontend bundle. → Acceptable; the existing `lightweight-charts` is already ~300KB.
- [OI heatmap colour scale] Normalising per-column means a strike with consistently low OI looks as dark as a high-OI strike in a quiet column. → Display absolute OI value in cell tooltip to compensate.

## Migration Plan

1. Backend: add `compute_gex()` to `analytics.py`, add two routes to `routes.py`. No DB schema changes.
2. Frontend: `npm install recharts` + `@types/recharts` (if needed), create route and three components, add sidebar link.
3. No migrations, no rollback risk — purely additive.

## Open Questions

- None.
