# bar-session-anchoring — minimal context

Read only these to work this change.

| File | Why |
|------|-----|
| `backend/pdp/market/bars.py` | `_bar_boundary:49` (epoch-anchored), `_bar_boundary_1d:58`, `_bar_boundary_1w:72`, `BarAggregator.on_tick` |
| `backend/pdp/market/CLAUDE.md` | Hot-path latency budget; the stale `market_bars` schema to fix |
| `backend/pdp/indicators/warmup.py` | Seeds `IndicatorEngine` from `market_bars` — consumer of the rebuilt series |
| `backend/pdp/market/bar_writer.py` | Batch writer to `market_bars` |
| `backend/strategies/directional_strangle_*.yaml` | `timeframes: [5m, 15m, 30m, 1H, 1D]` — which TFs must be correct |

## Key facts established during investigation
- Session open 09:15 IST = 03:45 UTC = 225 min past midnight. 1440 is divisible by 30 and 60 but not
  by 25 — so 30m/1H are *stably* misaligned and 25m *drifts daily*.
- Measured bucket of the session-open tick: 5m→09:15, 15m→09:15, 25m→09:15/09:00/09:10/08:55 on
  consecutive days, 30m→09:00, 1H→08:30.
- 15m and 5m already coincide with the session grid, so the fix is a no-op for them. That is the
  regression test.
- 1m bars are session-aligned by construction and dense — rebuild from them, not from Dhan
  (no API quota, reproducible).
- `market_bars` is a Mongo **timeseries** collection: no in-place update, delete-then-insert only.

## Related
Blocks `indicator-history-depth` (no point backfilling mis-anchored bars) and
`bias-input-completeness`. Expect archived backtest baselines to move; re-baseline before trusting
any later strategy change.
