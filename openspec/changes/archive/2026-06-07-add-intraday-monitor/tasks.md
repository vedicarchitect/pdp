## 1. Backend: Risk Kill-Switch Endpoint

- [x] 1.1 Add `POST /api/v1/risk/kill` route to FastAPI app
- [x] 1.2 Implement order cancellation logic (query `orders` table where `status='open'`, issue cancel via broker)
- [x] 1.3 Implement position flattening logic (query `positions` where `hold_until_next_open!=true`, issue market sells)
- [x] 1.4 Add atomic transaction wrapper (cancel all orders first, then flatten positions; if either fails, rollback)
- [x] 1.5 Add audit logging (timestamp, user_id, IP, cancelled_orders list, flattened_positions list)
- [x] 1.6 Add unit tests for kill-switch (success case, partial failure, empty order/position lists)
- [x] 1.7 Add integration test with paper broker (verify orders cancelled and positions closed correctly)

## 2. Backend: Daily Loss Cap Monitoring

- [x] 2.1 Add `/api/v1/settings/risk` GET endpoint to return configured loss caps (daily global, per-strategy)
- [x] 2.2 Add daily loss calculation query to `portfolio` module (sum realized loss + unrealized loss for today)
- [x] 2.3 Add per-strategy loss calculation (sum per `strategy_id` grouping)
- [x] 2.4 Add hard cap enforcement middleware (when daily loss > hard cap, auto-invoke kill-switch, log the trigger)
- [x] 2.5 Add loss reset logic at market open (reset `realized_loss_today` counter, keep positions)
- [x] 2.6 Add unit tests for loss calculation and hard cap triggers

## 3. Backend: WebSocket Broadcasting for Intraday

- [x] 3.1 Ensure `/ws/market` broadcasts all tick updates with < 50ms latency (already exists, verify)
- [x] 3.2 Ensure `/ws/orders` broadcasts order updates (new, fill, cancel) with < 50ms latency (already exists, verify)
- [x] 3.3 Ensure `/ws/portfolio` broadcasts position snapshots every 100ms (already exists, verify)
- [x] 3.4 Add P&L delta snapshots to portfolio feed (include realized_loss_today and per-strategy loss for frontend consumption)

## 4. Frontend: Intraday Page Scaffolding

- [x] 4.1 Create `/src/pages/Intraday.tsx` route component (assumes `add-frontend-skeleton` is done)
- [x] 4.2 Add Intraday to React Router config and main navigation
- [x] 4.3 Add WebSocket connection manager hook (`useIntraday WebSocketConnections`)
- [x] 4.4 Add error boundary and loading state (show "Connecting..." spinner until feeds are ready)
- [x] 4.5 Add TypeScript interfaces for Position, Strategy, and Alert data structures
- [x] 4.6 Add unit tests for page component mounting and WebSocket state management

## 5. Frontend: Position Display & P&L Aggregation

- [x] 5.1 Create `PositionTable.tsx` component to display strategy-grouped positions
- [x] 5.2 Implement P&L aggregation logic (hook that groups positions by `strategy_id` and sums Greeks)
- [x] 5.3 Add live update mechanism (re-aggregate on every market tick and fill event)
- [x] 5.4 Implement position expand/collapse (show individual legs on click)
- [x] 5.5 Add Greeks display (Δ, Γ, Θ, Vega columns for strategy row and per-leg)
- [x] 5.6 Add color coding (green for profit, red for loss, grey for neutral)
- [x] 5.7 Add unit tests for aggregation logic with mock WebSocket data

## 6. Frontend: Risk Monitoring & Alerts

- [x] 6.1 Create `RiskBanner.tsx` component (shows daily/per-strategy loss status)
- [x] 6.2 Add loss cap threshold logic (yellow at 80%, red at 100%, critical at 150%)
- [x] 6.3 Create `AlertPills.tsx` component for dismissible alerts (price hit, P&L, time-stop)
- [x] 6.4 Implement localStorage persistence for dismissed alerts (key: `intraday_dismissed_alerts`)
- [x] 6.5 Add alert trigger logic (check on every tick: price breaches, P&L crosses threshold, time elapsed)
- [x] 6.6 Add unit tests for alert state management and dismissal persistence

## 7. Frontend: Kill-Switch UI & Integration

- [x] 7.1 Create `KillSwitchButton.tsx` component (red, always visible, always enabled except during API call)
- [x] 7.2 Add confirmation dialog (modal: "Are you sure? This will cancel all orders and flatten all positions.")
- [x] 7.3 Implement `POST /api/v1/risk/kill` API call with error handling
- [x] 7.4 Display kill-switch response (toast: "Cancelled X orders, flattened Y positions")
- [x] 7.5 Add retry logic if kill-switch fails (exponential backoff, max 3 retries)
- [x] 7.6 Add unit tests for button interaction and API call flow

## 8. Frontend: WebSocket State Management

- [x] 8.1 Implement `useIntraday Feeds` hook to manage all 3 WebSocket connections
- [x] 8.2 Add reconnection logic with exponential backoff (1s → 2s → 4s → 8s)
- [x] 8.3 Add "Disconnected" badge UI component (shows when any feed is down)
- [x] 8.4 Implement data reconciliation on reconnect (fetch latest portfolio snapshot from `/api/v1/portfolio`)
- [x] 8.5 Add connection health monitoring (log warnings if any feed hasn't emitted data in 5 seconds)
- [x] 8.6 Add unit tests for reconnection logic and state sync

## 9. Frontend: Settings & Initialization

- [x] 9.1 Fetch `/api/v1/settings/risk` on page load
- [x] 9.2 Display loss cap values in a summary widget (daily cap, per-strategy caps)
- [x] 9.3 Add fallback defaults if settings unavailable (daily: -50% of capital, per-strategy: -30% of capital)
- [x] 9.4 Add visual indicator if settings are using defaults (warning badge)
- [x] 9.5 Add unit tests for settings fetch and fallback logic

## 10. Integration Testing

- [x] 10.1 Create end-to-end test scenario: user logs in → intraday page loads → WebSocket connects → positions appear
- [x] 10.2 Create scenario: simulate market tick → verify P&L updates within 100ms
- [x] 10.3 Create scenario: simulate order fill → verify position added and P&L recalculated
- [x] 10.4 Create scenario: loss approaching cap → verify yellow banner appears
- [x] 10.5 Create scenario: loss exceeds hard cap → verify kill-switch auto-triggers
- [x] 10.6 Create scenario: user clicks kill-switch manually → verify all orders cancelled and positions flattened
- [x] 10.7 Create scenario: WebSocket disconnects → verify "Disconnected" badge appears and kill-switch still works
- [x] 10.8 Create scenario: WebSocket reconnects → verify data re-syncs correctly

## 11. Documentation & Deployment

- [x] 11.1 Add endpoint documentation to `/api/v1/risk/kill` in API spec
- [x] 11.2 Document loss cap settings schema (where/how to configure in settings file or DB)
- [x] 11.3 Document intraday page routes and WebSocket feed format
- [x] 11.4 Add deployment checklist (ensure broker supports market orders, verify hard cap logic tested)
- [x] 11.5 Document runbooks for troubleshooting (kill-switch fails, WebSocket stuck disconnected, P&L divergence)
