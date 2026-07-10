# execution-console-daily-parity

**Minimal context set** (load only these when working this change):
- `proposal.md`, `design.md` (GOVERNANCE 5-phase), `tasks.md`,
  `specs/execution-console-daily-parity/spec.md`
- Backend: `strategies/directional_strangle.py` (`_await_fill_avg_px:643`, leg-open `_open_short`
  `:666`, `state():1035`, `_short_legs` init `:205`), `orders/paper.py` (`upsert_position:355`),
  `strategy/trade_ledger.py`, `strategy/routes.py` (`/strangle/trades:273`, `/legs:167`),
  `broker_sync/scheduler.py`, `broker_sync/service.py`, `broker_sync/routes.py`, `events/models.py`
- App: Live account tab + Execution tab widgets under `app/lib/`
- Cross-refs: change **#1 api-reliability-hardening** (owns the `upsert_position` C1 fix), change
  **#4 strategy-critical-data-alerts** (owns `emit_critical` + missing-data event types)

**Evidence:** 2026-07-08 monitor snapshot — SENSEX `entry —` with MTM `= -ltp × qty`
(`-16,324 = -204.05 × 80`); BANKNIFTY `-234,540` DONE (day-loss cap possibly tripped by phantom
loss); Live Dhan tab stale (broker sync is EOD-only at 15:45 IST).

**Ship order:** after #1 and #4 (it reuses #1's cost-basis fix and #4's critical-event plumbing).
Highest *operational* urgency of the set — it directly explains the daily P&L discrepancy and a
possible phantom day-loss-cap halt.
