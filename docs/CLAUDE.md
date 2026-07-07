# docs/ — Supplementary Documentation

Markdown docs for features/subsystems that need more detail than code comments.

## Files

| File | Purpose |
|------|---------|
| `ARCHITECTURE.md` | System design: three-tier arch, data flow, DB strategy, deployment blueprint |
| `RUNBOOK.md` | Operational reference: setup, running, monitoring, troubleshooting |
| `ALERTS.md` | Alert engine design: trigger types, evaluation loop, delivery mechanisms |
| `ALERTS_TESTING.md` | Manual test steps for verifying alert flows end-to-end |
| `backtest.md` | Backtest engine internals: bar replay, fill simulation, commission models |

## Where to go next

- **First time?** → [RUNBOOK.md](RUNBOOK.md) § 1–3 (setup + quickstart)
- **Running strategies?** → [RUNBOOK.md](RUNBOOK.md) § 6 (strategy operations)
- **Understanding the design?** → [ARCHITECTURE.md](ARCHITECTURE.md)
- **Working on a feature?** → Start at the appropriate [`backend/CLAUDE.md`](../backend/CLAUDE.md) or [`app/CLAUDE.md`](../app/CLAUDE.md)
- **Need context on a capability?** → See [`openspec/project.md`](../openspec/project.md) (tech stack, conventions, glossary)
