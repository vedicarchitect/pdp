## Why

The whole point of the backtest warehouse is to reproduce its edge in paper (and then live), but we
have no general way to compare a backtest against paper. The only comparison that exists,
`backtest/compare.py`, is a SuperTrend-only CLI for a single date that reads Mongo `paper_journal`
and writes nothing — it is not parameterized by strategy, not an API, and cannot align a multi-year
run against live paper results. We cannot answer "is paper tracking the ₹1.15 Cr backtest, and where
is it diverging and why." This change adds a generic, `strategy_id`-keyed backtest-vs-paper
comparison with per-day and minute-level alignment, and retires the ST-only script.

## What Changes

- **Per-strategy realized P&L query**: a service/query aggregating realized P&L per `strategy_id`
  over a date window from PostgreSQL (`trades ⨝ orders` on `order_id`, `orders.mode='PAPER'`, grouped
  by `orders.strategy_id`), mirroring `pdp/journal/stats.py:compute_daily_stats`. Add an index on
  `orders.strategy_id`.
- **vs-paper API**: `GET /api/v1/strangle-backtests/runs/{id}/vs-paper` aligns a run's equity/day
  series against the live paper results for the same `strategy_id` + window, surfacing per-day
  divergence.
- **Minute-level scan**: unify the backtest decision-event vocabulary (from `backtest-decision-trace`)
  with the live event vocabulary already emitted (`bias_evaluated`, `leg_open`, `leg_close`, `rolled`,
  `stop_gate_wait`, `bucket_change`, …) so each minute's backtest decision can be diffed against the
  live/paper decision for the same timestamp.
- **Root-cause hooks**: annotate divergence with likely causes by cross-referencing the gap radar
  (missing `cam_weekly`/`pcr`/VIX inputs) and the `bias_evaluated` votes — the same signals
  `/strangle:review` surfaces.
- **Retire the ST-only CLI**: `backtest/compare.py` is superseded by the generic API.
- **Skill**: `/backtest:vs-paper`.

## Capabilities

### New Capabilities
- `backtest-paper-comparison`: a generic, `strategy_id`-keyed comparison of a backtest run against
  paper — per-day P&L alignment, minute-level decision diff, and divergence root-causing.

### Modified Capabilities
- `backtest-compare`: the SuperTrend-only single-date comparison script is retired in favor of the
  generic API.

## Impact

- Backend: new comparison service + `GET /runs/{id}/vs-paper` in `pdp/backtest/warehouse_routes.py`;
  a per-`strategy_id` P&L aggregation over `pdp/orders/models.py` (Order/Trade join) reusing
  `pdp/journal/stats.py:compute_daily_stats` semantics; an Alembic index on `orders.strategy_id`;
  reuse of `backtest_decisions` (change 1) + live event stream for the minute-level diff; gap-radar
  cross-reference (change 2). Remove/deprecate `backtest/compare.py` + the `backtest:compare` task.
- Depends on change 1 (`backtest-decision-trace`) for the backtest side of the minute-level diff and
  change 2 (gap radar) for divergence root-causing.
- New skill: `/backtest:vs-paper`.
