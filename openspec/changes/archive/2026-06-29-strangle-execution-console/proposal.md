## Why

The directional strangle is the core PDP strategy — 5-year backtest P&L of Rs 1.36 cr. It is
paper-ready but has three gaps that limit confident real-world use: (1) several known parity
gaps between the live strategy and the backtest (vote breakdown, rollup, stop-gate, weekly
Camarilla, PCR), (2) no structured per-action log schema that can be fed to Claude for
trade-by-trade analysis and improvement, and (3) no API surface to see what the strategy is
doing in real time — current legs, M2M, bucket decisions, condition checks.

## What Changes

- **Fold in `live-directional-strangle-paper` parity tasks**: per-signal vote logging,
  rollup on premium decay, stop-gate re-entry cooldown, weekly Camarilla input, live PCR
  input, indicator timeframe key audit, and same-day parity check procedure.
- **Canonical per-action log schema**: every significant strategy action emits a structlog
  event with a typed `event_type` field and a consistent set of fields (legs, score, bucket,
  IST time, realized/unrealized P&L). Events also flow into a daily log file via the existing
  `StrategyDailyLog` for offline Claude analysis.
- **Execution console REST API**: `GET /api/v1/strangle/{status,legs,activity,stats}` gives
  a live view of running strategy state — current legs with LTP/MTM, bias score, active
  bucket, day P&L, and a ring buffer of recent decisions.
- **Archive `live-directional-strangle-paper`**: superseded by this chunk.

## Capabilities

### New Capabilities
- `strangle-execution-console`: paper-first execution console — parity hardening,
  canonical structured logging, in-memory execution state, and a read-only REST API that
  exposes everything the strategy is computing in real time.

### Modified Capabilities
_(none — existing strategy routes are extended, not altered)_

## Impact

- **`backend/pdp/strategies/directional_strangle.py`**: parity additions (rollup, stop-gate,
  cam_weekly, PCR), extended heartbeat/log calls, `state()` method, activity buffer.
- **`backend/pdp/signals/bias.py`**: no changes (votes already exposed in `BiasResult.votes`).
- **`backend/pdp/strategy/schemas.py`**: new `StrangleState`, `StrangleLeg`, `StrangleActivity`
  msgspec structs.
- **`backend/pdp/strategy/routes.py`**: four new read-only routes under `/api/v1/strangle/`.
- **`backend/pdp/strategy/log.py`**: `StrangleEventType` StrEnum; `emit_strangle_event` helper.
- **`backend/pdp/main.py`**: no new wiring needed (routes mount via existing strategy router).
- **`docs/RUNBOOK.md`**: §15 (paper startup checklist), §17 (weekly parity check), §18
  (reading the activity log / canonical event types reference).
- **Archived**: `openspec/changes/live-directional-strangle-paper/` → archive.
