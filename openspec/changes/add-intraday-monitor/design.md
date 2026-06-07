## Context

Intraday traders operate in a high-velocity environment requiring sub-second feedback loops. They need simultaneous visibility into:
- Open positions + live mark-to-market P&L per strategy
- Risk metrics (daily loss cap, per-strategy limits)
- Live market data (LTP, Greeks for options)
- Order fills and state changes
- System-wide kill-switch for emergency de-risking

The backend already provides `/ws/market` (ticks), `/ws/orders` (fills), and `/ws/portfolio` (P&L snapshots). The frontend must consolidate these into a low-latency dashboard and wire risk-enforcement endpoints.

## Goals / Non-Goals

**Goals:**
- Build a `/intraday` SPA page consuming existing WebSocket feeds (market, orders, portfolio)
- Display live positions, P&L, and Greeks grouped by strategy
- Enforce daily and per-strategy loss caps with real-time breach alerts
- Provide a global `POST /api/v1/risk/kill` endpoint that cancels all open orders and flattens intraday positions
- Alert system for price hits, P&L thresholds, and time-stops
- Sub-second visual update latency (all state changes via WebSocket, no polling)

**Non-Goals:**
- Order placement UI (use existing `/orders` page or future order-entry widget)
- Historical backtest or analysis views (separate from live monitoring)
- Risk-model calibration UI (risk caps configured via settings, not runtime tweaks)
- Multi-account risk aggregation (single account, single kill-switch)

## Decisions

**Decision 1: Single Unified WebSocket Connection**
- The frontend opens one persistent WebSocket connection to `/ws/market`, `/ws/orders`, and `/ws/portfolio` simultaneously, rather than separate streams per feed type.
- **Rationale:** Reduces connection overhead and simplifies synchronization. All state updates arrive on the same transport, making causality clearer (a fill impacts both orders and portfolio atomically from the frontend's perspective).
- **Alternative considered:** Separate WS streams per domain. Rejected because multi-stream sync adds complexity without performance benefit for intraday use case.

**Decision 2: P&L Aggregation at Frontend**
- The backend emits raw position + fill events; the frontend computes per-strategy P&L by rolling up open positions and MTM deltas.
- **Rationale:** Reduces backend load. The backend already computes live MTM for the portfolio; the frontend just needs to group by strategy_id and sum. Less state to keep synchronized.
- **Alternative considered:** Backend emits per-strategy P&L rollups directly. Rejected: tighter backend coupling, harder to refactor if strategy definition changes.

**Decision 3: Loss-Cap Enforcement as Dual-Path**
- **Soft cap (frontend):** User sees a breach warning 5 seconds before action (red banner, alert pill). Gives trader time to manually adjust.
- **Hard cap (backend, strict):** If loss exceeds cap, `POST /api/v1/risk/kill` is auto-invoked. No frontend override.
- **Rationale:** Intraday trading is fast. A fully backend-enforced cap would nuke positions on a temporary spike. Soft cap with 5-second warning gives humans a chance; hard cap is the final circuit-breaker.
- **Alternative considered:** Backend-only enforcement. Rejected: too brutal; traders would disable the cap.

**Decision 4: Kill-Switch as Atomic Multi-Step**
- `POST /api/v1/risk/kill` endpoint:
  1. Cancel all open orders (single query: `status='open'`)
  2. Flatten all intraday positions (issue market sells, skip overnight holds flagged `hold_until_next_open=true`)
  3. Log the action + caller (IP, user) for audit
  4. Return list of cancelled orders + flattened legs
- **Rationale:** Atomicity (all-or-nothing execution) prevents partial de-risking. Market orders flatten fastest in a panic scenario.
- **Alternative considered:** Gradual unwinding (send limit orders, wait for fills). Rejected: unacceptable latency in a kill-switch scenario.

**Decision 5: Alert Persistence in Browser LocalStorage**
- Alert dismissals and preferences (snooze time, alert types) stored in localStorage. No backend persistence.
- **Rationale:** Intraday alerts are session-scoped. Persistent backend storage would add API round-trips and database load for ephemeral state.
- **Alternative considered:** Store alert state in a Redis session. Rejected: overkill; alerts are local to the trader's browser.

## Risks / Trade-offs

**[Risk] Network partition or WebSocket disconnect during high volatility**
→ *Mitigation:* Frontend implements exponential backoff reconnect (1s → 2s → 4s → 8s) with visual "disconnected" badge. Kill-switch remains callable via HTTP POST (doesn't require WebSocket). Trader can manually invoke if needed.

**[Risk] Frontend P&L aggregation skew (if backend MTM and frontend grouping diverge)**
→ *Mitigation:* Backend emits a "portfolio snapshot" every 100ms; frontend reconciles per-strategy rollup against this ground truth. Any skew > ±1% triggers a silent re-sync.

**[Risk] Kill-switch latency if market is very slow to execute the flatten orders**
→ *Mitigation:* Kill-switch issues market orders (fastest fill), not cancellations. If a leg doesn't fill in 5 seconds, the order is cancelled and the next market order is re-issued (retry loop in backend). Worst-case: partial flatten + manual intervention needed (which is acceptable in an emergency scenario).

**[Risk] Dual-path loss-cap (soft frontend + hard backend) creates inconsistency if thresholds differ**
→ *Mitigation:* Frontend reads loss cap from settings on connect; backend uses same config. Both paths compute the same metric (daily realized + unrealized loss). They are guaranteed consistent at that instant.

## Migration Plan

1. **Phase 1: Backend risk endpoints** — Implement `POST /api/v1/risk/kill` as a standalone endpoint (no frontend UI yet). Test with manual curl/load-test.
2. **Phase 2: Frontend skeleton integration** — Assume `add-frontend-skeleton` is done (Vite, React, TanStack Query). Wire WebSocket hooks for market/orders/portfolio.
3. **Phase 3: P&L aggregation + display** — Build the intraday dashboard: position table (strategy grouped), live Greeks, P&L meter.
4. **Phase 4: Risk alerts + soft caps** — Add loss-cap banner, alert pills (price/P&L/time).
5. **Phase 5: Hard cap automation** — Wire hard cap breach → auto-invoke kill-switch.

Rollback: Disable `POST /api/v1/risk/kill` route (no data loss). Frontend can serve a "intraday unavailable" banner if needed.

## Open Questions

1. **Kill-switch order type:** Should the flatten orders be `market` (instant fill, unpredictable slippage) or `limit at mid + 1 pip` (safer but slower)? Assume `market` for now; revisit if slippage is unacceptable.
2. **Per-strategy risk cap override:** Can a trader adjust their per-strategy loss cap mid-day, or is it fixed at session start? Assume fixed (read-only from settings).
3. **Overnight vs. intraday position distinction:** How does the system know which positions are "intraday" (flatten on kill) vs. "swing" (hold overnight)? Assume a `hold_until_next_open` flag on each position; kill-switch skips flagged positions.
