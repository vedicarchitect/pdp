## Why

PDP has a fully functional paper broker, order routing, and alerts engine — but no frontend to use them interactively. Today, orders are placed only by automated strategies or CLI. Alerts are configured via API calls but have no CRUD UI. The user cannot:
- Manually place a paper trade from the UI
- View and manage open orders with cancel/modify
- Create, edit, or delete price/indicator alerts from the UI
- Use the strategy builder's "Trade This" handoff (proposal #2)

Sensibull offers virtual trading directly from the option chain. PDP should too — with the paper-first safety net already built in.

## What Changes

- **Order entry component**: A reusable order form component (`OrderEntry`) that submits to `POST /api/v1/orders`. Supports: security selection (searchable instrument picker), side (BUY/SELL), quantity (lots × lot_size), order type (MARKET/LIMIT), price (for LIMIT). Shows estimated cost and respects paper-first mode (displays PAPER badge, blocks LIVE unless `LIVE=true` in env).
- **"Trade from chain" integration**: The option chain (analytics page) and builder (proposal #2) can invoke the order entry component pre-populated with a leg's details.
- **Orders management panel**: View open orders (`GET /api/v1/orders`), active trades (`GET /api/v1/orders/trades`), current positions (`GET /api/v1/orders/positions`). Cancel open orders (`DELETE /api/v1/orders/{id}`). If `order-approval-center` is active, orders in `PENDING_APPROVAL` status display an amber badge and link to `/approvals` instead of showing a cancel button.
- **Alerts CRUD UI**: List alerts (`GET /api/v1/alerts`), create alert (`POST /api/v1/alerts`), edit, delete, toggle enabled. Alert types from existing backend. Live alert notifications via `/ws/alerts`.
- **Scanner view**: A simple table showing OI buildup classifications (from proposal #3) and IV extremes — a "scan for interesting setups" view built on existing analytics endpoints.

## Capabilities

### New Capabilities
- `order-entry-ui`: Reusable order entry form component with paper-first safety, security selection, and pre-population from chain/builder.
- `alerts-ui`: Alerts CRUD frontend with live WebSocket notification feed.

### Modified Capabilities
- `intraday-monitor`: Add "Place Order" action button to positions/trades tables, link to order entry.

## Impact

- `frontend/src/components/orders/OrderEntry.tsx` — NEW (order form component)
- `frontend/src/components/orders/OrderBook.tsx` — NEW (open orders table)
- `frontend/src/components/orders/TradesTable.tsx` — NEW (executed trades table)
- `frontend/src/components/orders/PositionsPanel.tsx` — NEW (current positions with P&L)
- `frontend/src/components/orders/InstrumentPicker.tsx` — NEW (searchable instrument selector)
- `frontend/src/routes/trading.tsx` — NEW (trading page with order entry + order book + positions)
- `frontend/src/routes/alerts.tsx` — NEW (alerts management page)
- `frontend/src/components/alerts/AlertsList.tsx` — NEW (alerts CRUD table)
- `frontend/src/components/alerts/AlertForm.tsx` — NEW (create/edit alert form)
- `frontend/src/components/alerts/AlertNotification.tsx` — NEW (live alert toast)
- `frontend/src/components/scanner/ScannerView.tsx` — NEW (OI/IV scanner table)
- `frontend/src/hooks/useAlertsWS.ts` — NEW (WebSocket hook for `/ws/alerts`)
- `frontend/src/hooks/useOrdersWS.ts` — NEW (WebSocket hook for `/ws/orders`)
- `frontend/src/components/Sidebar.tsx` — MODIFIED (add Trading, Alerts links)
- `frontend/src/components/intraday/*` — MODIFIED (add Place Order action)
- No backend changes — all endpoints already exist.
