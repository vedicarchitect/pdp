# Intraday Monitor — Spec

## Requirements

### Requirement: Intraday Dashboard Page
The system SHALL provide a dedicated `/intraday` SPA page for live position monitoring and risk management.

#### Scenario: User navigates to intraday dashboard
- **WHEN** a user navigates to `/intraday` route
- **THEN** the page loads and establishes WebSocket connections to `/ws/market`, `/ws/orders`, and `/ws/portfolio`

#### Scenario: Dashboard displays live positions
- **WHEN** WebSocket feeds are connected and active
- **THEN** the dashboard displays open positions grouped by strategy with live P&L, Greeks (for options), and mark-to-market values

---

### Requirement: Real-Time P&L Aggregation
The system SHALL compute and display per-strategy P&L in real-time by aggregating position and market data.

#### Scenario: P&L updates on new tick
- **WHEN** a new market tick arrives via `/ws/market`
- **THEN** affected positions' P&L is recalculated and dashboard updates within 100ms

#### Scenario: P&L updates on fill
- **WHEN** an order fill event arrives via `/ws/orders`
- **THEN** position is added/updated, per-strategy P&L is recalculated, and dashboard reflects new position immediately

---

### Requirement: Strategy-Grouped Position View
The system SHALL display positions grouped by strategy with aggregated Greeks and risk metrics.

#### Scenario: Multi-leg strategy display
- **WHEN** a strategy has multiple open positions (e.g., 1 call + 1 put + 2 futures)
- **THEN** all legs are shown under a single strategy row with combined Δ, Γ, Θ, Vega, and P&L totals

#### Scenario: Strategy expansion
- **WHEN** user clicks on a strategy row
- **THEN** individual legs expand inline showing quantity, entry price, current mark, and per-leg P&L

---

### Requirement: Daily Loss Cap Enforcement (Soft Alert)
The system SHALL monitor realized + unrealized daily loss and alert when approaching the configured cap.

#### Scenario: Loss threshold warning
- **WHEN** daily loss exceeds 80% of configured cap
- **THEN** a yellow warning banner appears at the top with "Approaching loss cap: {current} / {cap}"

#### Scenario: Loss cap breach detection
- **WHEN** daily loss exceeds 100% of configured cap
- **THEN** a red critical banner appears and the system triggers the hard cap enforcement (see hard cap requirement)

#### Scenario: Daily loss resets at market open
- **WHEN** market session opens the next day
- **THEN** daily realized loss counter resets to 0; unrealized loss continues from yesterday's close

---

### Requirement: Per-Strategy Loss Cap
The system SHALL enforce separate loss caps per strategy.

#### Scenario: Per-strategy cap exceeded
- **WHEN** a single strategy's daily loss exceeds its configured per-strategy cap
- **THEN** that strategy's row highlights in red and a yellow warning banner states which strategy exceeded its limit

#### Scenario: Hard cap breach for strategy
- **WHEN** a strategy's loss exceeds its hard cap (150% of configured limit)
- **THEN** all orders for that strategy are automatically cancelled and positions are flattened

---

### Requirement: Global Kill-Switch Endpoint
The system SHALL provide a `POST /api/v1/risk/kill` endpoint to cancel all open orders and flatten all intraday positions atomically.

#### Scenario: Kill-switch execution
- **WHEN** `POST /api/v1/risk/kill` is called with valid authentication
- **THEN** all open orders (status='open') are cancelled, all intraday positions are sold at market, and a response is returned with the list of cancelled orders and flattened legs

#### Scenario: Kill-switch preserves overnight holds
- **WHEN** kill-switch executes
- **THEN** positions flagged with `hold_until_next_open=true` are NOT flattened; only intraday positions are de-risked

#### Scenario: Kill-switch audit logging
- **WHEN** kill-switch is executed
- **THEN** the action is logged with timestamp, user ID/IP, and list of affected orders and positions for audit purposes

---

### Requirement: Alert System
The system SHALL provide dismissible alert pills for price hits, P&L thresholds, and time-stops.

#### Scenario: Price alert trigger
- **WHEN** a position's mark price hits a pre-configured alert threshold
- **THEN** an alert pill appears with the position name, current price, and alert threshold

#### Scenario: P&L threshold alert
- **WHEN** a strategy's P&L crosses a configured threshold (e.g., +5k or -10k)
- **THEN** an alert pill appears with the strategy name and current P&L value

#### Scenario: Time-stop alert
- **WHEN** a position has been open for longer than a configured time-stop duration
- **THEN** an alert pill appears suggesting the position should be closed

#### Scenario: Alert dismissal
- **WHEN** user clicks the X button on an alert pill
- **THEN** the pill is removed and the dismissal preference is stored in browser localStorage

---

### Requirement: WebSocket Reconnection
The system SHALL handle WebSocket disconnections gracefully with automatic reconnection.

#### Scenario: Connection lost
- **WHEN** WebSocket connection is dropped unexpectedly
- **THEN** a "Disconnected" badge appears in the UI and reconnection attempts begin with exponential backoff (1s → 2s → 4s → 8s)

#### Scenario: Reconnection successful
- **WHEN** reconnection succeeds
- **THEN** the "Disconnected" badge disappears and the dashboard re-syncs all data from the latest portfolio snapshot

#### Scenario: Kill-switch accessible when disconnected
- **WHEN** WebSocket is disconnected but authentication is valid
- **THEN** the kill-switch button remains callable via HTTP POST (independent of WebSocket state)

---

### Requirement: Settings Integration
The system SHALL read risk cap configuration from settings on page load.

#### Scenario: Loss cap configuration
- **WHEN** the intraday page loads
- **THEN** it reads the configured daily loss cap and per-strategy caps from settings (assume settings endpoint `/api/v1/settings/risk`)

#### Scenario: Settings unavailable
- **WHEN** settings are not available or invalid on load
- **THEN** the page displays a warning and uses safe defaults (daily cap = ₹50,000, per-strategy cap = ₹20,000)
