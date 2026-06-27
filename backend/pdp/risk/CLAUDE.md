# Risk & Journal Modules

---

## Risk (`src/pdp/risk/`)

| File | Size | Role |
|------|------|------|
| `service.py` | 6.3 KB | `KillSwitchService` — hard-cap auto-kill; flattens all positions via `OrderRouter` |
| `routes.py` | 2.2 KB | `risk_router` (`/risk/kill`), `settings_router` (`/settings/risk`) |

**Hard-cap wiring:** `PortfolioService.set_hard_cap_callback(fn, RISK_DAILY_LOSS_CAP_INR)` → calls `KillSwitchService.execute()` when daily loss > cap. Safe in paper mode — no real money.

**Manual kill:** `POST /risk/kill` triggers the same `KillSwitchService.execute()`.

Risk thresholds (settings):
- `RISK_DAILY_LOSS_CAP_INR` = 50,000 (hard cap → auto-kill)
- `RISK_PER_STRATEGY_LOSS_CAP_INR` = 20,000 (per-strategy soft cap)
- `RISK_SOFT_CAP_PCT` = 80.0 (% of cap that triggers warning)

---

## Journal (`src/pdp/journal/`)

| File | Size | Role |
|------|------|------|
| `service.py` | 5 KB | `JournalService` — subscribes to fill events; records fills; computes daily P&L + progress stats |
| `stats.py` | 2.9 KB | Daily aggregation helpers (win rate, gross profit/loss, profit factor) |
| `routes.py` | 0.6 KB | REST: `/journal/daily` — returns daily P&L stats |

**JournalService** stores to MongoDB (collection `paper_journal`). Starts always (paper and live). Subscribes to `OrdersHub` fill events.

Active spec: `paper-journal` (archived), `paper-pnl-correctness` (archived).
