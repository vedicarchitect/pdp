## Context

Alerts are a critical feature for active traders. Users monitor multiple positions/instruments and need to be notified when:
- Price crosses a threshold (stop-loss, profit targets)
- Greeks hit targets (delta, gamma, vega thresholds)
- P&L milestones (e.g., +$100 or -$200)

Currently, users must poll the UI manually. The alerts engine evaluates conditions on every tick/position update and pushes notifications to connected clients in real time.

The engine sits between the market engine (ticks) and position ledger (P&L), subscribing to both feeds and evaluating configured alert rules.

## Goals / Non-Goals

**Goals:**
- Evaluator subscribes to market ticks and position updates
- Evaluate alert conditions on every tick (latency budget: p99 ≤ 50ms)
- Push alerts to connected WebSocket clients on `/ws/alerts`
- Support multiple conditions: price, Greeks (delta/gamma/vega), P&L
- Store alerts in DB (security_id, condition, threshold, channels, status)
- Allow create/update/delete alert via REST API
- Deferred: Telegram/WhatsApp delivery (stub socket for future channels)

**Non-Goals:**
- Email or SMS delivery (Telegram deferred)
- Alert history/audit log (only current state in DB)
- Backtesting alerts (only live/paper evaluation)
- Custom scripted conditions (enum-based conditions only)

## Decisions

### Decision 1: Per-tick evaluation vs. batch evaluation
**Choice:** Per-tick evaluation.
**Rationale:** Alerts must fire immediately (p99 ≤ 50ms). Batch window (e.g., 100ms) introduces unacceptable latency.
**Alternative:** Batch every 100ms → simpler, but violates latency SLA; users miss fills/stops.

### Decision 2: Alert state machine (single vs. multi-leg)
**Choice:** Per-leg (security_id) independent state.
**Rationale:** Simplest model. Each (security_id, condition) is independent. No composite alerts.
**Alternative:** Composite alerts (e.g., "alert when ANY leg crosses") → complexity not justified yet.

### Decision 3: Database schema — normalized vs. denormalized
**Choice:** Single `alerts` table + subscribe to `positions`/`ticks` feeds.
**Rationale:** Avoids duplication; alert state is minimal (threshold + current value). Position/tick state lives in market engine.
**Alternative:** Duplicate price/Greeks in alerts table → more I/O, harder to sync.

### Decision 4: Channel abstraction
**Choice:** Channel enum (WS, Telegram, WhatsApp); start with WS only.
**Rationale:** Allows DB schema to be channel-agnostic. Deferred channels become pluggable later.
**Alternative:** Hardcode WS → tighter coupling, harder to extend.

### Decision 5: Condition types
**Choice:** Enum-based: PRICE_GT, PRICE_LT, DELTA_GT, DELTA_LT, PNL_GT, PNL_LT.
**Rationale:** Type safety, easy to validate. Covers 80% of use cases.
**Alternative:** Arbitrary expressions → opens door to abuse, harder to audit.

### Decision 6: Trigger logic — crossing vs. threshold
**Choice:** Crossing (state transition: ARMED → TRIGGERED → RESOLVED).
**Rationale:** Prevents alert spam. Once triggered, alert stays in TRIGGERED until condition is no longer true.
**Alternative:** Every tick → floods user with duplicates.

## Risks / Trade-offs

**[Risk] Per-tick evaluation overhead**
→ Mitigation: Condition evaluation is O(1) (subtract + compare). Bulk subscriptions to ticks/positions are handled by market engine's pub/sub, not polled.

**[Risk] Alert state divergence (DB vs. in-memory)**
→ Mitigation: Load alert on create/update; subscribe to feeds. No separate cache; state flows from feeds.

**[Risk] Telegram/WhatsApp deferred — incomplete feature**
→ Mitigation: Channel enum reserved; WS is production-ready. Telegram delivery is stub (logged, not sent).

**[Risk] No multi-leg composite alerts**
→ Mitigation: Acceptable for v1. Users create separate alerts per leg. Composite logic deferred to v2.

**[Risk] Stateless evaluator — alert state lost on restart**
→ Mitigation: Alerts are read from DB on startup. Recent ticks may be missed, but state is restored.

## Migration Plan

1. Create `alerts` table.
2. Deploy alerting evaluator (subscribes to ticks + positions).
3. Add REST endpoints: POST /alerts, PATCH /alerts/{id}, DELETE /alerts/{id}.
4. Add WebSocket channel `/ws/alerts` (authenticated, client ID → alerts subscription).
5. Test: Create alert, modify price, verify push on `/ws/alerts`.
6. No rollback risk; alerts are additive feature.

## Open Questions

- **Debounce/coalesce**: If price oscillates around threshold, fire once per second? (Deferred to tasks.)
- **Backfill on reconnect**: When WS client reconnects, send recent alert state? (Yes, deferred to impl.)
- **Alert lifecycle timeout**: Auto-resolve after 1 hour? (Deferred to v2.)
