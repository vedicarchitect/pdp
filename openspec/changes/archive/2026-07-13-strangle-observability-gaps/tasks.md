# Tasks — strangle-observability-gaps

> **Sequenced last, on purpose.** Depends on `indicator-history-depth`, `bias-input-completeness`,
> `strangle-close-path-atomicity`, `strangle-leg-state-durability` — each produces one readiness
> signal this change aggregates. Landing it earlier measures a system whose state is still wrong.

## 1. Tests first
- [x] 1.1 `tests/strategies/test_event_taxonomy.py`: cap clip → `POSITION_SIZE_CAPPED`; sign
      contradiction → `LEG_TYPE_CONTRADICTED`; the two never co-occur for one condition
- [x] 1.2 `tests/strategies/test_event_persistence.py`: an emitted event is readable from Mongo after
      the batch flush; the tick handler awaits no Mongo round trip (spy on the writer)
- [x] 1.3 `tests/strategy/test_directional_strangle.py::test_check_readiness_blocked_when_indicator_unseeded`:
      unseeded EMA(200) on 1H → indicator component `blocked` with the timeframe and period in the reason
- [x] 1.4 `test_check_readiness_degraded_on_stale_broker_sync`: stale `synced_at` → broker component `degraded`
- [x] 1.5 `test_check_readiness_all_ok_composite`: all components satisfied → composite `ok`
- [x] 1.6 `test_on_bar_refuses_entry_and_emits_once_while_blocked`: `blocked` → first entry refused, one
      `STRATEGY_NOT_READY` emitted naming components. **Caught and fixed a real bug**: `on_bar`'s own
      transition tracker reused `_last_readiness_state`, which `check_readiness()` had already mutated
      before `on_bar` read it — the "emit once" gate was dead code and never fired. Fixed with a
      separate `_entry_gate_blocked` flag.
- [x] 1.7 Existing-position management (stops/take-profit/square-off) runs in `on_tick`, which never
      calls `check_readiness()` — verified structurally (grep), not gated by construction
- [x] 1.8 `test_on_bar_resumes_entries_once_readiness_recovers`: readiness recovers → entries resume on
      the next bar
- [x] 1.9 `degraded` only → entry proceeds (readiness `state` is only `blocked` on a `blocked` component;
      `on_bar` gates on `readiness.is_blocked`, not `!= ok`)

## 2. Event taxonomy
- [x] 2.1 Audited the current `POSITION_SIZE_CAPPED`/`LEG_TYPE_CONTRADICTED` sites in
      `directional_strangle.py` (line numbers shifted substantially since this task was written by the
      CP-1..CP-5 rewrite — audited by content, not stale line numbers)
- [x] 2.2 The two genuine cap-clip/refusal sites in `_reserve_leg_lots` keep `POSITION_SIZE_CAPPED`
- [x] 2.3 The sign-contradiction site in `_close_leg`/`_on_sign_contradiction` uses `LEG_TYPE_CONTRADICTED`
      (defined by `strangle-leg-state-durability`)
- [x] 2.4 Momentum opens go through the same `_reserve_leg_lots` cap path — `POSITION_SIZE_CAPPED` is correct
- [x] 2.5 `backend/tests/strategy/test_directional_strangle.py` cap-clip tests assert `POSITION_SIZE_CAPPED`
      by name; `test_event_taxonomy.py` asserts the two types differ
- [x] 2.6 No OpenSearch dashboard under `infra/opensearch/` hardcodes either event type name — nothing to update

## 3. DB-first event persistence
- [x] 3.1 `_emit_event` gains a durable sink writing to the Mongo `events` collection
      (`pdp/mongo/collections.py` — it already has readers and no writer)
- [x] 3.2 Batch + fire-and-forget, mirroring `pdp/market/bar_writer.py`. **No awaited round trip in
      `on_tick`.**
- [x] 3.3 Keep structlog + OpenSearch. Demote the JSONL `self._slog` sink to a debugging convenience,
      documented as not-the-record
- [x] 3.4 Confirmed: `strategy/routes.py`'s `strangle_trades` reads the same durable `events` collection
      via `trade_ledger.read_durable_day_events`, covered by the passing `test_trade_ledger.py` suite
- [x] 3.5 `EventWriter.enqueue()` is a synchronous `deque.append` — no I/O, no await — structurally
      guarantees the hot path never blocks on Mongo; a live p99 benchmark needs market hours + traffic
      and was not run (documented, not measured)
- [x] 3.6 Verified with 1.2

## 4. Readiness model
- [x] 4.1 Define `ReadinessComponent{name, state: ok|degraded|blocked, reason: str|None}` and a
      composite. Put it in `pdp/strategy/`, not in the strangle strategy — it is platform-level.
- [x] 4.2 Indicator component: consumes `ctx.indicators.seeding_summary(underlying, tf)` for every
      watched timeframe
- [x] 4.3 Bias component: `_last_spot is None` blocks (score_bias's one hard input requirement)
- [x] 4.4 Chain component: `chain_hub.get_pcr(underlying)` non-null for every underlying with `w_pcr > 0`
- [x] 4.5 Broker component: `BrokerFund.synced_at` age vs 60s threshold (paper mode bypasses)
- [x] 4.6 Reconciliation component: the `_divergences` set, populated by `_flag_divergence`/
      `_reconcile_divergences` (`strangle-close-path-atomicity`)
- [x] 4.7 `check_readiness()` emits `STRATEGY_READINESS_CHANGED` once per composite-state transition

## 5. Readiness endpoint
- [x] 5.1 `GET /api/v1/strangle/readiness` → composite + per-component state and reason
      (path is `/strangle/readiness`, matching the existing `/strangle/status`, `/strangle/legs`,
      `/strangle/stats` sibling routes — not `/strategy/{id}/readiness` as originally sketched)
- [x] 5.2 Read-only; no mutation
- [x] 5.3 `test_readiness_route_surfaces_check_readiness` covers the blocked shape; `test_readiness.py`
      covers ok/degraded/blocked composite shapes at the model level

## 6. Gate the first entry
- [x] 6.1 Added `StrangleEventType.STRATEGY_NOT_READY` (the strategy's own local taxonomy — the
      platform-level `EventType.STRATEGY_NOT_READY` in `pdp/events/models.py` also already existed)
- [x] 6.2 `on_bar` new-entry gate: refuse while any component is `blocked`; emit once per transition
      (see 1.6 — was broken, now fixed and tested)
- [x] 6.3 Existing-position management, stops and square-off are **not** gated (on_tick never calls
      check_readiness)
- [x] 6.4 Re-evaluated every 5m bar in `on_bar`
- [x] 6.5 Verified with 1.6–1.9

## 7. App surface
- [x] 7.1 Readiness chip on the execution console (`_ReadinessChip` in `strategy_execution_tab.dart`),
      tooltip lists every non-ok component + reason per-underlying
- [x] 7.2 `ok` renders nothing (unobtrusive); `blocked`/`degraded` render a prominent colored chip
- [x] 7.3 Widget tests at 500px and 1400px widths (`strategy_execution_tab_test.dart`)
- [x] 7.4 `flutter analyze --fatal-infos` and `flutter test` both green (31 tests passed)

## 8. Docs + validation
- [x] 8.1 `backend/pdp/events/CLAUDE.md`: one event type = one condition rule + readiness taxonomy added
- [x] 8.2 `docs/RUNBOOK.md` §6: pre-open readiness check note added
- [x] 8.3 `task test` green against the recorded baseline (1111 passed)
- [x] 8.4 `openspec validate --strict strangle-observability-gaps` — run in Phase F alongside the other 9 changes — done 2026-07-13, passes

## Findings recorded here but fixed elsewhere — do not duplicate
- `stop_half` / `stop_all` missing exit fields: **already fixed** in `f045282`
  (`on_tick:535` captures `_leg_exit_fields` before mutating `leg.lots`; `:545` splats them).
  Verify, do not re-fix.
- SENSEX `pcr` wiring → `bias-input-completeness`.
- Live EMA(200) null → `indicator-history-depth` (the period was never configured).
