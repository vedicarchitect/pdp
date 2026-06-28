## Context

`DirectionalStrangle` is a working paper strategy: entry, exit, TP, stop, day-loss-cap, and
squareoff all function. `BiasResult.votes` already carries per-signal votes. `StrategyDailyLog`
already writes JSON lines to `logs/<strategy_id>/<date>.log`. The `live-directional-strangle-paper`
change has 7 parity tasks; none are implemented yet.

The missing pieces are: (1) the 7 parity gaps in the strategy, (2) a consistent log schema
so every action is machine-readable, and (3) an API surface so a Flutter screen (and a human)
can see what the strategy is doing right now.

## Goals / Non-Goals

**Goals:**
- Close all 7 parity gaps between live strategy and backtest replay.
- Every significant strategy action emits a structured log event with a typed `event_type`
  and a canonical field set — enough for offline Claude analysis (chunk 5).
- `GET /api/v1/strangle/{status,legs,activity,stats}` returns live execution state.
- Paper is always the default; `LIVE=1` + `BROKER=dhan` + creds required for live orders.
- Flutter consumption: the same API endpoints serve the Flutter screen in chunk 9.

**Non-Goals:**
- Manual order overrides or forced squareoff via API (chunk 9 scope).
- Persisting activity events to PostgreSQL or MongoDB (ephemeral in-memory; chunk 5 will add
  the durable log pipeline from the daily log files).
- Multi-underlying (BANKNIFTY, SENSEX) extension — NIFTY only in this chunk.
- Weekly Camarilla from an external feed — read from the existing indicator engine's
  `ind.pivots(sid, "1w")` after subscribing a 1w bar.

## Decisions

### D1 — Parity tasks implemented directly in `DirectionalStrangle`
No new module. All 7 parity gaps are fixed inline in `directional_strangle.py`:
- `bias_votes` log: expose `result.votes` dict in the existing `bias_evaluated` log call.
- `leg_status` heartbeat: emit after every `bias_evaluated` with legs + LTP + MTM.
- Rollup: in `on_tick`, when a short leg's LTP < `roll_trigger_prem` (default 20), close
  the leg, find the next OTM strike with premium ≥ `roll_target_min_prem` (default 50),
  reopen. Same for its matching hedge. Log `rolled` event.
- Stop-gate: `_stop_gate: dict[str, dict]` keyed by `opt_type` (`"PE"`, `"CE"`).
  After a stop, record `{exit_px, sid, n_below: 0}`. On each 5m bar: get LTP of the stopped
  sid; if below exit_px increment `n_below`, else reset; clear gate when `n_below >= 3`.
  Gate `_open_short` per side; log `stop_gate_wait`.
- Weekly Cam: subscribe `self.sid` on `"1w"` in `on_init`; read `ind.pivots(self.sid, "1w")`
  in `_build_bias_inputs`.
- Live PCR: read `ind.pcr(self.sid)` if available, else keep `pcr=None`. No new polling loop
  — whatever the indicator engine already computes on the options chain is used.
- Timeframe key audit: in `on_init`, after subscribe, assert `ind.ema(self.sid, "5m")` etc.
  do not raise; log `strategy_warmup_check` with which timeframes resolved.

Alternative considered: separate `StrangleParity` mixin class. Rejected — the parity logic is
tightly coupled to `_short_legs` and `_stop_gate` state; a mixin would require back-references.

### D2 — Canonical log schema via `emit_strangle_event` helper
Add `StrangleEventType` StrEnum and `emit_strangle_event(ctx, event_type, **fields)` to
`pdp/strategy/log.py`. The helper calls `ctx.log.info(event_type, **fields)` AND calls
`ctx.daily_log.write({...})` so the event lands in both structlog (stderr/JSON) and the
daily file. Every action method in `DirectionalStrangle` switches its ad-hoc `ctx.log.info`
calls to `emit_strangle_event`.

Canonical fields on every event: `event_type`, `strategy_id`, `account_id`, `snapshot_date`,
`ist_time`, `underlying`, `spot` (where available), `score`, `bucket`.
Action-specific extra fields are appended (e.g. `leg_open` adds `sid`, `opt_type`, `strike`,
`lots`, `entry_price`, `is_hedge`).

Alternative considered: msgspec struct per event type. Rejected — structlog dicts are simpler
to evolve and the daily log file is the durable record; strict typing belongs in chunk 5's
analysis schema.

**Implementation note:** `emit_strangle_event` became `_emit_event(self, …)` — a private
method on `DirectionalStrangle` rather than a standalone function in `log.py`. This was
necessary because the helper needs instance state (`self._activity`, `self._slog`). Only
`StrangleEventType` and `StrangleActivityEvent` live in `log.py` / `schemas.py`.
`StrangleActivityEvent(msgspec.Struct)` provides a typed shape for the activity API response.

### D3 — In-memory execution state + activity ring buffer
`DirectionalStrangle` gains:
- `_activity: collections.deque[dict]` (maxlen=200) — every `emit_strangle_event` call appends.
- `state() -> dict` method returning: `mode`, `strategy_id`, `bucket`, `score`, `legs`
  (list of leg dicts), `day_realized`, `day_unrealized`, `day_pnl`, `done_for_day`,
  `vix_now`, `started_at`.

`StrategyHost.get_strategy(id)` already exists; the REST routes call it to retrieve the
`DirectionalStrangle` instance and read `.state()` and `._activity`.

State is lost on API restart. That is acceptable: paper mode restarts are rare and the daily
log file has the durable record.

### D4 — Read-only REST API under `/api/v1/strangle/`
Four routes added to `pdp/strategy/routes.py`:
- `GET /api/v1/strangle/status` — strategy mode, bucket, score, done_for_day, vix_now, started_at.
- `GET /api/v1/strangle/legs` — current open legs with entry_price, LTP (last tick), MTM, side, strike.
- `GET /api/v1/strangle/activity?n=50` — last N events from the ring buffer (default 50, max 200).
- `GET /api/v1/strangle/stats` — day realized, day unrealized, total P&L, trade count, leg count by side.

No write operations in this chunk. The `strategy_id` is resolved from query param (default: the
first loaded strategy whose class is `DirectionalStrangle`).

LTP for the legs API: read from `StrategyHost._last_tick_cache` (or equivalent) keyed by
`security_id`. If LTP not yet seen, return `null` for MTM — the field is nullable.

### D5 — Paper gate unchanged
`LIVE=1` env gate already exists in `PaperBroker` / `OrderRouter`. Status response includes
`mode: "paper" | "live"`. No change to the gate logic.

## Risks / Trade-offs

- **LTP cache staleness**: if the strategy hasn't received a tick for a leg recently, the
  MTM in `GET /legs` will be stale or null. Mitigation: document the null case in the API
  response schema; Flutter screen shows "—" for null MTM.
- **Weekly Camarilla warmup**: `ind.pivots(sid, "1w")` may return `None` on first startup
  if the 1w bar hasn't closed yet. Mitigation: treat `None` as missing input (already the
  pattern throughout `_build_bias_inputs`); log `cam_weekly_missing` once on first `None`.
- **PCR freshness**: options chain polling frequency may lag behind 5m bars. Mitigation:
  use whatever the engine has; if `None`, the PCR vote is skipped (already the bias-engine
  convention for missing signals).
- **Activity buffer lost on restart**: any mid-day restart wipes the ring buffer. Mitigation:
  the daily log file is the durable record; the ring buffer is a convenience window for the UI.
- **Route conflict**: `/api/v1/strategy/{id}` already exists. New routes use `/api/v1/strangle/`
  (no `{id}` segment) to avoid ambiguity. Multi-strategy support (chunk 15) will add an `id`
  param later.

## Open Questions

- **PCR indicator**: does `ind.pcr(sid)` exist on `IndicatorEngine`? If not, fall back to
  reading from `OptionsChainPoller.latest_pcr()`. Resolve during implementation.
- **LTP cache key**: confirm whether `StrategyHost` exposes a `last_ltp(security_id)` method
  or if `DirectionalStrangle` needs to maintain its own `_ltp_cache: dict[str, float]`.
  The tick handler already tracks `_vix_now` — same pattern for option legs.
