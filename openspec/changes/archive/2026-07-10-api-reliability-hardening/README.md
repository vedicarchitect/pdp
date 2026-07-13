# api-reliability-hardening

**Minimal context set** (load only these when working this change):
- `proposal.md` (why/what/impact), `design.md` (GOVERNANCE 5-phase), `tasks.md`, `specs/api-hardening/spec.md`
- Backend: `backend/pdp/deps.py` (new), `orders/`, `journal/`, `alerts/evaluator.py`,
  `risk/service.py`, `portfolio/service.py`, `backtest/routes.py`, `options/gap_backfill.py`,
  `market/dhan_ws.py`, `db/session.py`, `mongo/client.py`, `settings.py`
- Reviews behind this change: FastAPI review (20 findings), whole-backend finder pass (C1–C13),
  Postgres/Mongo pool findings (P1/M1/M3) — see the approved plan.
- Sibling change **#4 `strategy-critical-data-alerts`** owns the CRITICAL-event surfacing that
  this change's un-swallowed money/data failures publish to.

**Ship order:** first (independent, highest value, lowest risk). Does **not** depend on the
worker split; the process split (`api-worker-decoupling`) reuses this change's validated models.
