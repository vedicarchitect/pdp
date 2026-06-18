# order-entry-ui Specification

## Purpose
TBD - created by archiving change 2026-06-17-virtual-trading-and-alerts-ui. Update Purpose after archive.
## Requirements
### Requirement: Order entry UI component

The system SHALL provide a reusable `OrderEntry` dialog component for placing orders via `POST /api/v1/orders`. The component SHALL include: a searchable instrument picker, side selector (BUY/SELL), quantity input, order type selector (MARKET/LIMIT), price input (for LIMIT orders), estimated cost display, and a prominent PAPER/LIVE mode badge. The component SHALL support a `prefill` prop for pre-populating fields when invoked from the option chain or strategy builder.

#### Scenario: Place a paper market order
- **WHEN** a user opens OrderEntry, selects NIFTY, chooses BUY MARKET, enters 1 lot, and clicks Submit
- **THEN** `POST /api/v1/orders` is called with the order details, a success Toast appears, and the dialog closes

#### Scenario: OrderEntry shows PAPER badge
- **WHEN** the system is running in paper mode (default)
- **THEN** the OrderEntry dialog displays a green "PAPER" badge at the top

#### Scenario: OrderEntry shows LIVE warning
- **WHEN** the system is running with `LIVE=true`
- **THEN** the OrderEntry dialog displays a red "LIVE" badge with warning text "Real money orders"

#### Scenario: Pre-populated from option chain
- **WHEN** a user clicks "Trade" on a CE strike at 24900 in the option chain
- **THEN** the OrderEntry dialog opens with security pre-filled to NIFTY 24900 CE, side pre-filled to BUY

---

### Requirement: Trading page with orders, trades, and positions

The system SHALL provide a `/trading` route displaying: open orders in a DataTable with cancel action, recent trades in a DataTable, and current positions in a DataTable with live MTM P&L. A "New Order" button SHALL open the OrderEntry dialog. Order and position data SHALL update in real-time via `/ws/orders` WebSocket.

#### Scenario: View open orders
- **WHEN** a user navigates to `/trading` with 3 open orders
- **THEN** the Open Orders table displays 3 rows with Time, Symbol, Side, Qty, Type, Price, Status columns

#### Scenario: Pending approval order shown with correct state
- **WHEN** the `order-approval-center` change is active and an order has status `PENDING_APPROVAL`
- **THEN** the order row displays a "Pending Approval" Badge (amber) and the Cancel action is replaced with a link to `/approvals`

#### Scenario: Cancel an open order
- **WHEN** a user clicks Cancel on an open order with status `OPEN`
- **THEN** `DELETE /api/v1/orders/{id}` is called, the order disappears from the table, and a Toast confirms cancellation

#### Scenario: Positions update in real-time
- **WHEN** a fill event arrives via `/ws/orders`
- **THEN** the Positions table updates the MTM P&L without a manual refresh

---

### Requirement: Instrument search picker

The system SHALL provide an `InstrumentPicker` component that searches `GET /api/v1/instruments?search={query}` with 300ms input debounce. Each result SHALL display the instrument name, exchange segment as a Badge, and security_id. The picker SHALL be reusable across OrderEntry, AlertForm, and any future forms.

#### Scenario: Search for an instrument
- **WHEN** a user types "NIFTY" in the InstrumentPicker
- **THEN** matching instruments are displayed after a 300ms debounce, showing name and exchange Badge

