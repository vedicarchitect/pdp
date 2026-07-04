## Why

A backtest is only as trustworthy as the data behind it, yet today nothing surfaces *what data
exists* or *what's missing*. Coverage is recomputed ad hoc inside the gap-backfill core, the audit
script is NIFTY-only, and the console has no way to show that (say) weekly Camarilla, VWAP inputs,
VIX, or futures are absent for a date — or to fix it in a click. Users must reproduce the ₹1.15 Cr
edge in paper, but silent input gaps are exactly what break parity (the `/strangle:review` skill
already flags `cam_weekly missing` / `pcr None`). This change gives a coverage/gap radar across all
indices and input families, with one-click delta-fill, and finishes the multi-index self-heal.

## What Changes

- **Coverage API**: a new `GET /api/v1/coverage` returning, per underlying (NIFTY/BANKNIFTY/SENSEX)
  and per input family, min/max date, trade-day counts, gap-day ranges, and a coverage %. Reuses the
  existing `gap_backfill.days_missing`/`expected_contracts`/`trading_days`.
- **Gap radar over backtest input families**: promote `pdp/backtest/completeness.py`'s spot gate into
  a per-family readiness view — spot (drives VWAP/EMAs/ORB), options chain, India VIX, `index_levels`
  (daily/weekly Camarilla), and futures — so the console can flag "VWAP missing", "weekly Camarilla
  missing", "futures missing", "VIX missing" per (index, date), each with a one-click backfill action.
- **One-click delta-fill for all indices**: plumb `symbol` through the housekeeping backfill handlers
  so `POST /api/v1/housekeeping/{task}` delta-fills any index/family (`--to today --only-missing`),
  streaming progress over `/ws/jobs`. Add levels/VIX backfill to the same task surface.
- **Multi-index self-heal**: implement the already-specced per-underlying gap-heal so BANKNIFTY and
  SENSEX self-heal in the background, not just NIFTY.
- **OpenSearch**: a new `data-coverage` family + a coverage dashboard (auto-loaded by `task search:init`).
- **Skills**: `/data:coverage` (read-only report) and `/data:gapfill` (radar → backfill → re-check).

## Capabilities

### New Capabilities
- `market-data-coverage`: per-underlying, per-family data-availability + gap-radar API, one-click
  delta-fill wiring, and a coverage dashboard/observability feed.

### Modified Capabilities
- `housekeeping-api`: the backfill task endpoints accept a `symbol` (NIFTY/BANKNIFTY/SENSEX) so
  delta-fill can target any index, and add level/VIX backfill tasks.
- `multi-index-warehouse`: the self-healing gap-fill loop runs for BANKNIFTY/SENSEX (remove the
  "skip if multi-index-options-backfill not landed" escape now that it has landed).

## Impact

- Backend: new coverage module/route (reuse `pdp/options/gap_backfill.py`,
  `pdp/backtest/completeness.py`, `pdp/warehouse/service.py:UNDERLYING_REGISTRY`);
  `pdp/housekeeping/{routes,tasks.py}` (symbol param + new tasks);
  `pdp/warehouse/service.py:_run_gap_backfill` (multi-index); generalize
  `scripts/audit_options_coverage.py` off its NIFTY hardcode; `pdp/observability/{mappings,sinks}.py`
  (`data-coverage` family); `infra/opensearch/dashboards/NN_data_coverage.ndjson`.
- APIs: `GET /api/v1/coverage`; `POST /api/v1/housekeeping/{task}` gains `symbol`.
- Data families reported include futures; if a futures source isn't yet ingested, the radar reports
  it as missing and its backfill action is a follow-up hook (documented in design).
- New skills: `/data:coverage`, `/data:gapfill`.
