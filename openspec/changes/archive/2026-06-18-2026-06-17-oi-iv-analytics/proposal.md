## Why

PDP's analytics page shows max-pain, GEX, OI heatmap, and PCR — but lacks the OI/IV signals that active options traders rely on most. Platforms like Quantsapp show OI buildup classification (long buildup, short buildup, short covering, long unwinding), multi-strike OI change series, ATM straddle price history, and IV rank/percentile. Sensibull adds FII/DII data for institutional flow context. Without these signals, PDP users must monitor external tools to read market structure.

## What Changes

- **OI buildup classification** in `src/pdp/options/analytics.py`: Classify strikes into long buildup (price ↑ + OI ↑), short buildup (price ↓ + OI ↑), short covering (price ↑ + OI ↓), and long unwinding (price ↓ + OI ↓) using price + OI deltas from `option_bars` or `option_chains` snapshots.
- **Multi-strike OI change series**: New endpoint returning OI change (absolute and %) for multiple strikes over configurable intervals (5m, 15m, 1H, 1D).
- **ATM straddle price history**: Track ATM straddle premium over the trading day using option chain snapshots. New endpoint returns time-series of ATM CE + PE premium sum.
- **IV rank and percentile**: Compute current IV's rank and percentile relative to historical IV (from `option_bars` / `expired_option_bars`). IV rank = (current - min) / (max - min) over N days; IV percentile = % of days below current IV.
- **FII/DII data (pluggable, stubbed)**: Define a `FIIDIISource` interface with a `fetch()` method. Ship with a stub that returns mock/empty data and a note that a concrete source must be configured. The frontend degrades gracefully (hides the FII/DII panel if no data).
- **Frontend**: Expand `/analytics` with new panels — OI buildup table, multi-strike OI chart, straddle history chart, IV rank gauge, FII/DII summary (if available).

## Capabilities

### New Capabilities
- `fii-dii-data`: Pluggable FII/DII data source interface with stub implementation.

### Modified Capabilities
- `options-analytics`: OI buildup classification, multi-strike OI series, straddle history, IV rank/percentile endpoints.
- `options-analytics-tools`: Frontend analytics panels expanded with new visualizations.

## Impact

- `src/pdp/options/analytics.py` — MODIFIED (add OI buildup, straddle history, IV rank functions)
- `src/pdp/options/routes.py` — MODIFIED (add oi-buildup, straddle-history, iv-history, fii-dii endpoints)
- `src/pdp/options/fii_dii.py` — NEW (interface + stub)
- `tests/options/test_analytics.py` — MODIFIED (add tests for new functions)
- `frontend/src/components/analytics/OIBuildupPanel.tsx` — NEW
- `frontend/src/components/analytics/StraddleHistoryChart.tsx` — NEW
- `frontend/src/components/analytics/IVRankGauge.tsx` — NEW
- `frontend/src/components/analytics/MultiStrikeOIChart.tsx` — NEW
- `frontend/src/components/analytics/FIIDIIPanel.tsx` — NEW (conditional render)
- `frontend/src/routes/analytics.tsx` — MODIFIED (integrate new panels)
- No new external Python dependencies.
