## REMOVED Requirements

### Requirement: Paper-vs-backtest comparison script
**Reason**: Superseded by the generic, `strategy_id`-keyed `backtest-paper-comparison` capability. The
SuperTrend-only, single-date CLI (`backtest/compare.py`) cannot compare an arbitrary strategy or a
multi-year run against live paper, reads Mongo `paper_journal` instead of the PostgreSQL ledger, and
is not an API.
**Migration**: Use `GET /api/v1/strangle-backtests/runs/{id}/vs-paper` (and the per-strategy paper
P&L query) for any strategy and window; use the `/backtest:vs-paper` skill for an interactive
comparison. The `backtest:compare` Taskfile task and `backtest/compare.py` are removed.

### Requirement: Comparison output format
**Reason**: The structured text report belonged to the retired CLI; the generic capability returns
aligned per-day and minute-level series via the API for the UI to render, not a fixed console table.
**Migration**: Consume the `vs-paper` API response (aligned backtest and paper series + divergence)
or the `/backtest:vs-paper` skill output.
