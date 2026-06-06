## ADDED Requirements

### Requirement: Live broker activation gate

The system SHALL activate the live Dhan broker only when `LIVE` is true AND `BROKER == "dhan"` AND Dhan credentials (`DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`) are configured. In every other case orders SHALL route to the paper engine. The default configuration SHALL be paper.

#### Scenario: Live activated with full configuration

- **WHEN** the app starts with `LIVE=1`, `BROKER=dhan`, and Dhan credentials set
- **THEN** a `DhanBroker` instance is started and registered with the `OrderRouter`
- **AND** order responses carry the header `X-Trade-Mode: LIVE`

#### Scenario: Missing credentials falls back to paper

- **WHEN** the app starts with `LIVE=1` and `BROKER=dhan` but `DHAN_CLIENT_ID` is empty
- **THEN** no `DhanBroker` is started and orders route to the paper engine with `X-Trade-Mode: PAPER`

### Requirement: Live order routing to Dhan

When the active broker is `dhan`, the `OrderRouter` SHALL route `add_order` and `cancel_order` to the `DhanBroker`, which places the order via the Dhan REST SDK, persists the returned broker order id on the order, and sends the platform `client_order_id` as the Dhan `tag` for correlation.

#### Scenario: Order placed on Dhan stores broker order id

- **WHEN** a valid order is placed while the active broker is `dhan`
- **THEN** the Dhan `place_order` call is invoked with the mapped parameters and the order's `client_order_id` as `tag`
- **AND** the value returned in `data.orderId` is persisted to `orders.broker_order_id`

#### Scenario: Placement failure rejects the order

- **WHEN** the Dhan `place_order` call returns `status = "failure"`
- **THEN** the order transitions to `REJECTED` with `reject_reason` set from the broker remarks and no broker order id is stored

#### Scenario: Cancel routed to Dhan

- **WHEN** `DELETE /api/v1/orders/{id}` is called for an OPEN order whose broker is `dhan`
- **THEN** the Dhan cancel REST call is invoked with the stored `broker_order_id`

### Requirement: Dhan field and cost mapping

The system SHALL map platform order fields to Dhan SDK parameters: order type (`MARKET`→`MARKET`, `LIMIT`→`LIMIT`, `SL`→`STOP_LOSS`, `SL_M`→`STOP_LOSS_MARKET`), product (`NRML`→`MARGIN`, `MIS`→`INTRADAY`, `CNC`→`CNC`), and exchange segment (`NSE_CUR`→`NSE_CURRENCY`, others passed through). The `broker_costs` table SHALL contain rows for `broker = "dhan"` so charges are computed for live fills.

#### Scenario: SL order type mapped

- **WHEN** an order with `order_type = "SL"` and `product = "NRML"` is placed on Dhan
- **THEN** the Dhan request uses `order_type = "STOP_LOSS"` and `product_type = "MARGIN"`

#### Scenario: Live fill charges populated

- **WHEN** a live Dhan trade fills for `instrument_type = OPTIDX`
- **THEN** `trades.charges` is computed from the `broker_costs` row for `(dhan, OPTIDX)` and is greater than zero

### Requirement: Live fills from order-update stream

The system SHALL consume Dhan order-update events over the broker WebSocket. On an update with status `TRADED`, the system SHALL fetch the trade book for that broker order id, insert a `Trade` row, transition the `Order` to `FILLED`, upsert the `Position` using the same weighted-average / realize-on-reduce accounting as the paper engine, and publish the corresponding events to `/ws/orders`. Status `CANCELLED` and `REJECTED` SHALL transition the order accordingly.

#### Scenario: TRADED alert produces a fill

- **WHEN** an order-update event with status `TRADED` arrives for a known `broker_order_id`
- **THEN** the trade book is fetched, a `Trade` row is created with the broker fill price and quantity, the `Order` becomes `FILLED`, and the `Position` is updated
- **AND** `/ws/orders` clients receive `trade` and `position` events

#### Scenario: REJECTED alert transitions order

- **WHEN** an order-update event with status `REJECTED` arrives for a known `broker_order_id`
- **THEN** the `Order` transitions to `REJECTED` and a `/ws/orders` order event is published

### Requirement: Startup fill reconciliation

On startup the live broker SHALL reconcile orders that may have been filled or cancelled while the process was down, by fetching the broker order list and trade book and applying any fills not yet recorded locally.

#### Scenario: Missed fill recovered on startup

- **WHEN** the `DhanBroker` starts and an order that was `OPEN` locally is `TRADED` at the broker
- **THEN** the corresponding `Trade` and `Position` rows are created and the `Order` is transitioned to `FILLED` before live updates resume
