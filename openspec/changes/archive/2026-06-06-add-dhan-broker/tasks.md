## 1. Schema

- [x] 1.1 Alembic migration `0007_dhan_broker.py`: add nullable `broker_order_id VARCHAR(64)` to `orders` (+ index)
- [x] 1.2 Same migration: seed `broker_costs` rows for `broker='dhan'` — EQUITY, FUTIDX/FUTSTK, OPTIDX/OPTSTK (NSE+BSE charge schedules)
- [x] 1.3 Add `broker_order_id` field to the `Order` SQLAlchemy model in `src/pdp/orders/models.py`

## 2. DhanBroker adapter

- [x] 2.1 `src/pdp/orders/dhan_broker.py` — `DhanBroker` with `start`/`stop`/`add_order`/`cancel_order`/`set_hub` (mirrors `PaperBroker`)
- [x] 2.2 Executor wrapper: run all synchronous `dhanhq` REST calls via `loop.run_in_executor(None, ...)`
- [x] 2.3 `_to_dhan_params()` field mapping — order_type (SL→STOP_LOSS, SL_M→STOP_LOSS_MARKET), product (NRML→MARGIN, MIS→INTRADAY, CNC→CNC), exchange_segment (NSE_CUR→NSE_CURRENCY)
- [x] 2.4 `add_order()` — call `place_order(...)` with `tag = client_order_id`, store `data['orderId']` in `broker_order_id`; on `status='failure'` transition order to REJECTED with broker remarks
- [x] 2.5 `cancel_order()` — call Dhan cancel REST with stored `broker_order_id`
- [x] 2.6 OrderSocket bridge — run `OrderSocket` (`wss://api-order-update.dhan.co`) in a worker thread, hand events back via `loop.call_soon_threadsafe` (same pattern as `DhanTickerAdapter`)
- [x] 2.7 `_fill()` on `TRADED` — fetch `get_trade_book(broker_order_id)`, create `Trade`, transition `Order`→FILLED, upsert `Position`, publish to `OrdersHub`
- [x] 2.8 Handle `CANCELLED` / `REJECTED` order-update statuses
- [x] 2.9 Startup reconciliation — `get_order_list()` + `get_trade_book()` to apply fills missed while down

## 3. Shared accounting

- [x] 3.1 Factor position-upsert + charges logic from `src/pdp/orders/paper.py` so both brokers reuse weighted-avg / realize-on-reduce + `broker_costs` cost model

## 4. Routing & wiring

- [x] 4.1 `src/pdp/orders/router.py` — `OrderRouter.__init__` accepts `dhan_broker: DhanBroker | None`; route `add_order`/`cancel_order` to it when `broker == "dhan"`
- [x] 4.2 `src/pdp/main.py` — construct + `start()` `DhanBroker` only when `LIVE` and `BROKER=="dhan"` and `DHAN_CLIENT_ID` set; `stop()` in lifespan shutdown
- [x] 4.3 Confirm `X-Trade-Mode: LIVE` header is emitted when the live broker is active

## 5. Tests

- [x] 5.1 Unit: `_to_dhan_params()` mapping coverage (all order_type / product / segment combos)
- [x] 5.2 Integration: mocked `dhanhq` client → `POST /api/v1/orders` asserts `place_order` args + `broker_order_id` stored
- [x] 5.3 Integration: inject `order_alert` TRADED → assert `Trade` row, `Order` FILLED, `Position` upsert, `/ws/orders` events
- [x] 5.4 Integration: placement `status='failure'` → order REJECTED with reason
- [x] 5.5 Unit: startup reconciliation applies a missed fill exactly once (idempotent)

## 6. Validation

- [x] 6.1 `openspec validate --strict add-dhan-broker`
- [x] 6.2 Live smoke (gated): `LIVE=1 BROKER=dhan` place a small MARKET order, verify on Dhan dashboard, restart to verify reconciliation
