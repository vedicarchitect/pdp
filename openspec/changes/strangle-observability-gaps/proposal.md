# strangle-observability-gaps

## Why

The 2026-07-09 incident ran for a full session before anyone knew it was happening. Not because the
strategy was silent — it emitted thousands of events — but because nothing the strategy emits answers
the two questions an operator actually asks: *is this thing healthy right now?* and *what exactly
went wrong?*

**One event type carries three unrelated meanings.** `EventType.POSITION_SIZE_CAPPED` is emitted from
five sites in `directional_strangle.py`:

| Site | Actual condition |
|------|------------------|
| `:1616`, `:1634` | Open refused or clipped because the per-sid lot cap was reached |
| `:1370`, `:1422` | The broker's net-qty sign contradicts the leg's assumed type on close |
| `:1157` | Momentum leg condition |

The second of these is a *data-corruption* alarm — the leg is misclassified, the durable state is
wrong. The first is a *risk-limit working as designed*. They arrive on the same channel with the same
name and the same severity. A dashboard counting `POSITION_SIZE_CAPPED` cannot distinguish "the cap
did its job" from "the position tracking is broken", and neither can an alert rule.

**Strategy events never reach a database.** `_emit_event` (`:604-624`) fans out to structlog, a JSONL
file via `self._slog`, and an in-memory `_activity` deque. That is all. It does not write Mongo or
PostgreSQL — which is precisely why `_rehydrate_legs` reading a Mongo `events` collection for
`leg_open` documents finds nothing, forever (see `strangle-leg-state-durability`). This violates the
project's DB-first rule, and it means post-incident reconstruction depends on a local JSONL file that
rotation, a changed working directory, or a container restart can lose.

**There is no readiness gate.** Whether a strategy is fit to trade on a given morning depends on
things scattered across five subsystems:

- indicator warmup depth (`indicator-history-depth`)
- bias-input satisfiability (`bias-input-completeness`)
- option-chain availability for the underlying (`bias-input-completeness`)
- broker-sync mirror freshness (`broker-sync-visibility` — `last_state_refresh_at`)
- leg reconciliation against the broker (`strangle-close-path-atomicity`)

Each of those changes emits its own signal. **Nothing aggregates them.** The strategy will happily
begin trading at 09:15 with an unseeded EMA(200), two abstaining bias inputs, a stale broker mirror
and an un-reconciled leg — exactly the configuration it was in on 2026-07-09 — and the only way to
find out is to read five different log streams.

This change is deliberately sequenced **last**. Fixing measurement before fixing the thing being
measured just yields higher-fidelity readings of a system that is still miscounting. Every signal
this change aggregates is produced by one of the changes that precede it.

## What Changes

- **Split the overloaded event type.** `POSITION_SIZE_CAPPED` retains only its risk-limit meaning
  (open refused or clipped at the cap). The close-path sign contradiction becomes
  `LEG_TYPE_CONTRADICTED` (defined in `strangle-leg-state-durability`). Audit all five call sites and
  give each the event that describes what actually happened. Update the four assertions in
  `tests/strategy/test_directional_strangle.py:953-1025`, which currently assert the overloaded name
  and would otherwise pass through the rename unchanged.

- **Persist strategy events DB-first.** `_emit_event` writes to a durable store — the Mongo `events`
  collection that `get_events_collection` already exposes and that two call sites already read — in
  addition to structlog and OpenSearch. The JSONL sink becomes a debugging convenience, not the
  record. This closes the dead-read loop directly.

- **Add a pre-session readiness check.** A single `GET /api/v1/strategy/{id}/readiness` and a
  corresponding startup log line report, per strategy: indicator seeding completeness, bias-input
  satisfiability, chain availability per underlying, broker-mirror freshness, and leg-vs-broker
  reconciliation. Each is `ok` / `degraded` / `blocked` with a reason string.

- **Gate the first entry of the day on readiness.** The strategy refuses to open its first leg of a
  session while any readiness component is `blocked`, emits `STRATEGY_NOT_READY` naming the
  components, and re-checks each bar. `degraded` warns and proceeds. Existing positions are still
  managed and squared off — a blocked strategy stops *opening*, never stops *protecting*.

- **Surface readiness in the app.** The execution console shows the readiness state per strategy so
  the operator sees `blocked: ema_200 unseeded on 1H` at 09:10, not a mysteriously idle strategy at
  10:30.

## Impact

- **Affected specs:** `strangle-observability-gaps` (new). Amends `openspec/specs/events/spec.md` and
  `openspec/specs/strategy-registry/spec.md`.
- **Affected code:** `backend/pdp/strategies/directional_strangle.py` (`_emit_event:604`, the five
  `POSITION_SIZE_CAPPED` sites at `:1157`, `:1370`, `:1422`, `:1616`, `:1634`),
  `backend/pdp/events/models.py`, `backend/pdp/strategy/routes.py` (readiness endpoint),
  `backend/pdp/mongo/collections.py` (`get_events_collection:361` gains a writer),
  `backend/tests/strategy/test_directional_strangle.py:953-1025`,
  `app/lib/features/manage/` (readiness surface), `infra/opensearch/` (dashboard for the new taxonomy).
- **Sequenced last, deliberately.** Depends on `indicator-history-depth`,
  `bias-input-completeness`, `strangle-close-path-atomicity` and `strangle-leg-state-durability`,
  each of which produces one of the readiness signals. Landing it earlier would mean measuring a
  system whose state is still wrong.
- **`_emit_event` sits near the hot path.** It is called from `on_tick`. The Mongo write must be
  fire-and-forget through a batching writer (mirror `BarWriter`), never an awaited round-trip inside
  the tick handler. Confirm tick→WS p99 ≤ 50ms after the change (non-negotiable #5).
- **Two findings from the 2026-07-09 review are handled elsewhere, not here.** The missing
  `stop_half` / `stop_all` exit fields were already fixed in `f045282` — `on_tick:535,545` captures
  `_leg_exit_fields` before mutating `leg.lots` and splats them into the event. The SENSEX `pcr`
  wiring and the live EMA(200) null are causes, not measurement gaps, and belong to
  `bias-input-completeness` and `indicator-history-depth` respectively. Recorded here so the trail is
  not lost.
- Ties into [[opensearch_log_pipeline]] and [[event_publisher]].
