## Why

The platform can place and fill orders on the paper engine but has no live execution path. `select_broker()` already resolves to `("dhan", LIVE)` when `LIVE=1` and `BROKER=dhan`, yet no `DhanBroker` exists to receive those orders. This change adds the live Dhan adapter so real orders can route to the exchange while paper remains the default.

## What Changes

- New `DhanBroker` adapter implementing the same interface as `PaperBroker` (`start`/`stop`/`add_order`/`cancel_order`/`set_hub`), so `OrderRouter` selects it purely on the order's `broker` field.
- `OrderRouter` accepts an optional `dhan_broker` and routes `add_order`/`cancel_order` to it when `broker == "dhan"`; paper stays the default.
- Orders are placed via the `dhanhq` REST SDK (synchronous → wrapped in `run_in_executor`); the returned broker order id is persisted on the order, and our `client_order_id` is sent as the Dhan `tag` for correlation.
- Live fills arrive over Dhan's order-update WebSocket (`OrderSocket`); on a `TRADED` alert the adapter fetches the trade book, records the `Trade`, transitions the `Order` to FILLED, upserts the `Position`, and publishes to `/ws/orders` — reusing the paper-fill accounting.
- Startup reconciliation pulls the order list + trade book to recover fills missed while the process was down.
- New nullable `broker_order_id` column on `orders`; `broker_costs` seeded with real Dhan NSE/BSE charge schedules for EQUITY / FUT* / OPT*.
- `main.py` wires `DhanBroker` only when `LIVE` and `BROKER == "dhan"` and Dhan credentials are present (**paper-first preserved**).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `order-execution`: add the live-broker (Dhan) execution path — broker-field routing to a live adapter, `broker_order_id` persistence and correlation via `tag`, fills sourced from the broker order-update stream + trade book, startup fill reconciliation, and Dhan field/cost mapping. Paper behavior and the broker-mode gate are unchanged.

## Impact

- New `src/pdp/orders/dhan_broker.py`; modified `src/pdp/orders/router.py` and `src/pdp/main.py`.
- New Alembic migration `0007` (orders.broker_order_id + dhan `broker_costs` rows).
- Depends on archived `order-execution` (paper engine, positions, cost model) and the `dhanhq` SDK already in `pyproject.toml`.
- No change to MongoDB/Timescale work — orders/trades/positions remain in PostgreSQL.
