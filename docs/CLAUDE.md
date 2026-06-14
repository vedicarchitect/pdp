# docs/ — Supplementary Documentation

Markdown docs for features/subsystems that need more detail than code comments.

## Files

| File | Purpose |
|------|---------|
| `ALERTS.md` | Alert engine design: trigger types, evaluation loop, delivery |
| `ALERTS_TESTING.md` | Manual test steps for verifying alert flows |
| `backtest.md` | Backtest engine internals: bar replay, fill simulation, commissions |
| `supertrend_short_strategy.md` | Strategy logic: entry/exit rules, scale-in, stop mechanics |

## Note

For **operational** docs (how to run things), see [RUNBOOK.md](../RUNBOOK.md) at the root.
For **architectural** context, see [openspec/project.md](../openspec/project.md).
This folder is for deeper implementation notes that don't fit as code comments.
