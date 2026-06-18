## 1. Order entry component

- [x] 1.1 Create `frontend/src/components/orders/InstrumentPicker.tsx` — searchable dropdown querying `GET /api/v1/instruments?search={query}` with 300ms debounce; shows name, exchange Badge, security_id
- [x] 1.2 Create `frontend/src/components/orders/OrderEntry.tsx` — Dialog with: InstrumentPicker, Side toggle (BUY green / SELL red), Qty (NumberField), Order Type (MARKET/LIMIT select), Price (NumberField, shown for LIMIT), estimated cost display, PAPER/LIVE Badge, Submit button
- [x] 1.3 Wire Submit to `POST /api/v1/orders` via TanStack Query mutation; show Toast on success/error; close dialog on success
- [x] 1.4 Support `prefill` prop — pre-populate fields when invoked from chain/builder
- [x] 1.5 Display paper-first safety: PAPER Badge (green) or LIVE Badge (red + warning text)

## 2. Trading page

- [x] 2.1 Create `frontend/src/routes/trading.tsx` — `createFileRoute('/trading')` with trading layout
- [x] 2.2 Create `frontend/src/components/orders/OrderBook.tsx` — DataTable of open orders from `GET /api/v1/orders`; columns: Time, Symbol, Side, Qty, Type, Price, Status, Cancel button
- [x] 2.3 Wire Cancel button: `DELETE /api/v1/orders/{id}`, invalidate query, show Toast
- [x] 2.4 Create `frontend/src/components/orders/TradesTable.tsx` — DataTable of executed trades from `GET /api/v1/trades`; columns: Time, Symbol, Side, Qty, Fill Price, Charges
- [x] 2.5 Create `frontend/src/components/orders/PositionsPanel.tsx` — DataTable of current positions from `GET /api/v1/positions`; columns: Symbol, Side, Qty, Avg Price, MTM P&L, Actions (close)
- [x] 2.6 Add "New Order" button to Trading page header — opens OrderEntry dialog

## 3. WebSocket hooks

- [x] 3.1 Create `frontend/src/hooks/useOrdersWS.ts` — connect to `/ws/orders`, on fill/cancel events invalidate orders/trades/positions TanStack Query caches
- [x] 3.2 Create `frontend/src/hooks/useAlertsWS.ts` — connect to `/ws/alerts`, on alert trigger show Toast notification with alert name and triggered value
- [x] 3.3 Wire `useOrdersWS()` in Trading page — orders/positions update in real-time
- [x] 3.4 Wire `useAlertsWS()` in Alerts page and globally (Toast shows regardless of current page)

## 4. Alerts page

- [x] 4.1 Create `frontend/src/routes/alerts.tsx` — `createFileRoute('/alerts')` with alerts layout
- [x] 4.2 Create `frontend/src/components/alerts/AlertsList.tsx` — DataTable of alerts from `GET /api/v1/alerts`; columns: Symbol, Condition, Channels, Status (Badge: ARMED/TRIGGERED/RESOLVED), Actions (Edit, Delete)
- [x] 4.3 Create `frontend/src/components/alerts/AlertForm.tsx` — Dialog for create/edit: InstrumentPicker, condition (PRICE_GT/PRICE_LT/etc.), threshold value
- [x] 4.4 Wire Create: `POST /api/v1/alerts`, invalidate query, show Toast
- [x] 4.5 Wire Edit: `PATCH /api/v1/alerts/{id}` (threshold only), invalidate query
- [x] 4.6 Wire Delete: `DELETE /api/v1/alerts/{id}`, confirmation Dialog, invalidate query
- [x] 4.7 Status display: ARMED (green) / TRIGGERED (warning) / RESOLVED (outline)
- [x] 4.8 Create `frontend/src/components/alerts/AlertNotification.tsx` — presentational component for triggered alert toast content

## 5. Scanner view

- [x] 5.1 Create `frontend/src/components/scanner/ScannerView.tsx` — fetches OI buildup (from `/oi-buildup`) and IV rank (`/iv-history`); displays a DataTable: Strike, Type, OI Buildup (color-coded Badge), IV Rank, Action (opens OrderEntry)
- [x] 5.2 Add Scanner as a tab on the Trading page
- [x] 5.3 Graceful degradation: if proposal #3 endpoints return 404, show "Analytics upgrade required" message

## 6. Handoff integration

- [x] 6.1 Update builder "Trade This" button — LegTable `onTrade` prop invokes OrderEntry with prefilled leg details (strike, side, qty=lots×lotSize, price=premium)
- [x] 6.2 Add "Trade" action to OI Buildup panel rows on the analytics page — ShoppingCart icon opens OrderEntry with prefilled strike/type/side
- [x] 6.3 Add "Close" action to intraday monitor position rows — invoke OrderEntry with prefilled security/side/qty

## 7. Sidebar integration

- [x] 7.1 Add "Trading" link to sidebar under TRADING group (icon: `ArrowUpDown` from lucide)
- [x] 7.2 Add "Alerts" link to sidebar under SYSTEM group (icon: `Bell` from lucide — currently AlertTriangle, functional)

## 8. Final verification

- [x] 8.1 Run `cd frontend && npm run build` — clean build ✓ (4.15s, 2545 modules)
- [x] 8.2 Run `cd frontend && npx tsc --noEmit` — no type errors (included in build)
- [x] 8.3 Playwright suite 18/18 passing — shell, analytics, portfolio, instruments, backtest, dialog accessibility
- [x] 8.4 AlertForm/AlertsList fixed to match backend schema (PATCH, condition/threshold)
- [x] 8.5 OrderEntry shows PAPER badge via useTradeMode; exchange_segment + product included in POST
