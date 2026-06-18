## Context

PDP's backend already provides everything needed for order entry and alerts — the frontend just needs to consume these existing endpoints:

**Orders**: `POST /api/v1/orders` (place), `GET /api/v1/orders` (list), `DELETE /api/v1/orders/{id}` (cancel), `GET /api/v1/orders/trades`, `GET /api/v1/orders/positions`. WebSocket: `/ws/orders` (fill/cancel events), `/ws/portfolio` (P&L updates).

**Alerts**: `POST /api/v1/alerts` (create), `GET /api/v1/alerts` (list), `PUT /api/v1/alerts/{id}` (update), `DELETE /api/v1/alerts/{id}` (delete). WebSocket: `/ws/alerts` (triggered alert notifications).

**Instruments**: `GET /api/v1/instruments` (search/list).

The paper broker (`PaperBroker`) is the default execution engine. Live trading requires `LIVE=true` + `BROKER=dhan` + credentials — the order entry UI must clearly indicate the active mode and prevent accidental live orders.

## Goals / Non-Goals

**Goals:**
- Let users place paper orders manually from the UI.
- Display open orders, trades, and positions in a unified trading view.
- Provide a complete alerts CRUD interface with live notifications.
- Enable "trade from chain" and "trade from builder" handoffs.
- Show a scanner for OI/IV setups.

**Non-Goals:**
- Live order routing (gated behind env vars, not UI controls).
- Order modification (cancel and re-place for now).
- Complex alert conditions (indicator crossovers, multi-condition) — future enhancement.
- Basket orders / multi-leg simultaneous execution — future enhancement.

## Decisions

### D1: OrderEntry as a reusable modal component

The `OrderEntry` component is a `Dialog` (from UI kit) that can be invoked from multiple contexts:
- Trading page: "New Order" button
- Option chain: click a strike → OrderEntry pre-populated
- Builder: "Trade This" button → OrderEntry pre-populated per leg
- Intraday monitor: "Place Order" action on a position row

```tsx
interface OrderEntryProps {
  open: boolean;
  onClose: () => void;
  prefill?: {
    securityId: string;
    side: "BUY" | "SELL";
    qty: number;
    orderType: "MARKET" | "LIMIT";
    price?: number;
  };
}
```

### D2: Paper-first safety in the UI

The order entry form displays:
- A prominent `PAPER` or `LIVE` Badge at the top
- Paper mode: green badge, orders go to PaperBroker
- Live mode: red badge + warning text "LIVE TRADING — Real money orders"
- The mode is read from existing ModeBanner / settings endpoint

### D3: Trading page layout

```
┌───────────────────────────────────────────────┐
│ Trading                        [+ New Order]  │
├─────────────────┬─────────────────────────────┤
│ Open Orders     │  Positions                  │
│ ┌─────────────┐ │  ┌─────────────────────────┐│
│ │DataTable    │ │  │DataTable with live MTM  ││
│ │Cancel button│ │  │P&L from /ws/portfolio   ││
│ └─────────────┘ │  └─────────────────────────┘│
├─────────────────┤                             │
│ Recent Trades   │  Scanner                    │
│ ┌─────────────┐ │  ┌─────────────────────────┐│
│ │DataTable    │ │  │OI Buildup / IV rank     ││
│ │Fill details │ │  │filtered actionable list ││
│ └─────────────┘ │  └─────────────────────────┘│
└─────────────────┴─────────────────────────────┘
```

### D4: Alerts page layout

```
┌───────────────────────────────────────────────┐
│ Alerts                        [+ New Alert]   │
├───────────────────────────────────────────────┤
│ Active Alerts                                 │
│ ┌───────────────────────────────────────────┐ │
│ │Name │ Type │ Condition │ Status │ Actions│  │
│ │NIFTY│Price │ > 25000   │ Active │ ✏️ 🗑 │  │
│ │BNF  │Price │ < 50000   │ Paused │ ✏️ 🗑 │  │
│ └───────────────────────────────────────────┘ │
├───────────────────────────────────────────────┤
│ Alert History (triggered alerts)              │
│ ┌───────────────────────────────────────────┐ │
│ │Time │ Name │ Condition │ Value │ Action  │  │
│ └───────────────────────────────────────────┘ │
└───────────────────────────────────────────────┘
```

### D5: InstrumentPicker for security selection

A searchable dropdown that queries `GET /api/v1/instruments?search={query}` with debounced input. Shows instrument name, exchange segment (Badge), and security_id. Used by OrderEntry and AlertForm.

### D6: Scanner is a lightweight view built on proposal #3 endpoints

The scanner fetches OI buildup (`/oi-buildup`) and IV rank (`/iv-history`) and displays a filtered table of actionable setups: strikes with strong buildup, extreme IV, etc. This is a read-only view — clicking a row could open OrderEntry pre-populated.

### D7: WebSocket hooks for real-time updates

- `useOrdersWS()`: Connects to `/ws/orders`, updates order/trade/position queries on fill/cancel events
- `useAlertsWS()`: Connects to `/ws/alerts`, shows Toast notification on alert trigger, updates alerts list

## Risks / Trade-offs

- **Live trading safety**: The UI must never make it "easy" to accidentally place a live order. Paper mode is default; live mode requires env var + visual warnings. Consider adding a confirmation dialog for live orders.
- **Order modification**: Not supported in v1 — cancel and re-place. This matches PaperBroker behavior.
- **Multi-leg execution**: The builder's "Trade This" places each leg as a separate order. Simultaneous multi-leg execution (basket) is a future enhancement.

## Migration Plan

1. Build OrderEntry component (reusable dialog).
2. Build InstrumentPicker component.
3. Build Trading page (order book, trades, positions).
4. Build Alerts page (CRUD + live notifications).
5. Build Scanner view.
6. Add WebSocket hooks.
7. Wire "trade from chain" and "trade from builder" handoffs.
8. Add sidebar links.

## Open Questions

- None — all backend endpoints exist and are documented.
