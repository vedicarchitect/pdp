# Tasks — strangle-observability-gaps

> **Sequenced last, on purpose.** Depends on `indicator-history-depth`, `bias-input-completeness`,
> `strangle-close-path-atomicity`, `strangle-leg-state-durability` — each produces one readiness
> signal this change aggregates. Landing it earlier measures a system whose state is still wrong.

## 1. Tests first
- [ ] 1.1 `tests/strategies/test_event_taxonomy.py`: cap clip → `POSITION_SIZE_CAPPED`; sign
      contradiction → `LEG_TYPE_CONTRADICTED`; the two never co-occur for one condition
- [ ] 1.2 `tests/strategies/test_event_persistence.py`: an emitted event is readable from Mongo after
      the batch flush; the tick handler awaits no Mongo round trip (spy on the writer)
- [ ] 1.3 `tests/strategy/test_readiness.py`: unseeded EMA(200) on 1H → indicator component `blocked`
      with the timeframe and period in the reason
- [ ] 1.4 Stale `last_state_refresh_at` → broker component `degraded`
- [ ] 1.5 All components satisfied → composite `ok`
- [ ] 1.6 `blocked` → first entry refused, one `STRATEGY_NOT_READY` emitted naming components
- [ ] 1.7 `blocked` with open positions → stop / take-profit / square-off still execute
- [ ] 1.8 Readiness recovers at 10:00 → entries resume on the next bar
- [ ] 1.9 `degraded` only → warning emitted, entry proceeds

## 2. Event taxonomy
- [ ] 2.1 Audit all five `POSITION_SIZE_CAPPED` sites: `directional_strangle.py:1157`, `:1370`,
      `:1422`, `:1616`, `:1634`. Write down the actual condition at each before changing any.
- [ ] 2.2 `:1616`, `:1634` (cap clip) keep `POSITION_SIZE_CAPPED`
- [ ] 2.3 `:1370`, `:1422` (sign contradiction) → `LEG_TYPE_CONTRADICTED`
      (defined by `strangle-leg-state-durability`)
- [ ] 2.4 `:1157` (momentum) — determine which condition it is and assign accordingly
- [ ] 2.5 **Update `backend/tests/strategy/test_directional_strangle.py:953, 979, 1003, 1025`** —
      they assert the overloaded name and will otherwise pass through the rename unchanged, which is
      exactly how an overloaded event survives a refactor
- [ ] 2.6 Update the OpenSearch dashboards in `infra/opensearch/` for the new taxonomy

## 3. DB-first event persistence
- [ ] 3.1 `_emit_event:604-624` gains a durable sink writing to the Mongo `events` collection
      (`pdp/mongo/collections.py:361` — it already has readers and no writer)
- [ ] 3.2 Batch + fire-and-forget, mirroring `pdp/market/bar_writer.py`. **No awaited round trip in
      `on_tick`.**
- [ ] 3.3 Keep structlog + OpenSearch. Demote the JSONL `self._slog` sink to a debugging convenience,
      documented as not-the-record
- [ ] 3.4 Confirm the document shape matches what `strategy/routes.py:332` and (post-durability)
      any remaining reader expect
- [ ] 3.5 Measure tick→WS p99 before and after; assert ≤ 50ms (non-negotiable #5)
- [ ] 3.6 Verify with 1.2

## 4. Readiness model
- [ ] 4.1 Define `ReadinessComponent{name, state: ok|degraded|blocked, reason: str|None}` and a
      composite. Put it in `pdp/strategy/`, not in the strangle strategy — it is platform-level.
- [ ] 4.2 Indicator component: consumes the seeding summary from `indicator-history-depth` task 6
- [ ] 4.3 Bias component: consumes the satisfiability check from `bias-input-completeness` task 5
- [ ] 4.4 Chain component: `chain_hub.get_pcr(underlying)` non-null for every underlying with `w_pcr > 0`
- [ ] 4.5 Broker component: `last_state_refresh_at` from `GET /api/v1/broker-sync/status`
      (**not** `last_run` — the intraday path writes no run row; see `broker-sync-visibility`)
- [ ] 4.6 Reconciliation component: the `LEG_STATE_DIVERGED` check from
      `strangle-close-path-atomicity` task 6
- [ ] 4.7 Log the composite once at startup, per strategy

## 5. Readiness endpoint
- [ ] 5.1 `GET /api/v1/strategy/{id}/readiness` → composite + per-component state and reason
- [ ] 5.2 One mutation per route — this is a read; do not fold a refresh into it (non-negotiable #3)
- [ ] 5.3 API test: blocked, degraded and ok shapes

## 6. Gate the first entry
- [ ] 6.1 Add `STRATEGY_NOT_READY` to `pdp/events/models.py`
- [ ] 6.2 `on_bar` new-entry gate: refuse while any component is `blocked`; emit once per
      `(strategy, blocking-set)` change, not once per bar
- [ ] 6.3 Existing-position management, stops and square-off are **not** gated
- [ ] 6.4 Re-evaluate readiness each bar; resume when unblocked
- [ ] 6.5 Verify with 1.6–1.9

## 7. App surface
- [ ] 7.1 Readiness chip per strategy on the execution console; expandable reasons
- [ ] 7.2 `ok` is unobtrusive; `blocked` is prominent
- [ ] 7.3 Widget test at both narrow and wide viewports (see `flutter-execution-tab-layout` for why
      the narrow case needs its own test)
- [ ] 7.4 `cd app` then `flutter analyze`; `cd app` then `flutter test` — both green

## 8. Docs + validation
- [ ] 8.1 `backend/pdp/events/CLAUDE.md`: one event type = one condition; the readiness taxonomy
- [ ] 8.2 `docs/RUNBOOK.md` §pre-open: check readiness before the session, not after
- [ ] 8.3 `task test` green against the recorded baseline
- [ ] 8.4 `openspec validate --strict strangle-observability-gaps` passes

## Findings recorded here but fixed elsewhere — do not duplicate
- `stop_half` / `stop_all` missing exit fields: **already fixed** in `f045282`
  (`on_tick:535` captures `_leg_exit_fields` before mutating `leg.lots`; `:545` splats them).
  Verify, do not re-fix.
- SENSEX `pcr` wiring → `bias-input-completeness`.
- Live EMA(200) null → `indicator-history-depth` (the period was never configured).
