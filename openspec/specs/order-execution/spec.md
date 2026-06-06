## Requirement: Order placement endpoint

The system SHALL expose `POST /api/v1/orders` accepting `{client_order_id, security_id, exchange_segment, side, qty, order_type, price?, trigger_price?, product, strategy_id?}` and persisting a new order row with status `NEW`.

#### Scenario: Successful placement

- **WHEN** `POST /api/v1/orders` is called with a valid MARKET order body and unique `client_order_id`
- **THEN** the response is HTTP 201 with the created order, status `OPEN`, broker `paper`
- **AND** the response header `X-Trade-Mode: PAPER` is present

#### Scenario: Idempotent placement

- **WHEN** the same `client_order_id` is submitted twice
- **THEN** the second response returns the original order with HTTP 200 (not duplicated)

## Requirement: Deterministic paper fills

The system SHALL fill paper orders deterministically from the live tick stream: MARKET orders fill at the next tick with configured slippage; LIMIT orders fill when the LTP crosses the limit price; SL / SL-M orders trigger when LTP crosses the trigger price.

#### Scenario: MARKET fills on next tick

- **WHEN** a MARKET BUY for 1 lot of security 13 is placed and the next tick has LTP 24500
- **THEN** within 1 second a `trade` row exists with `fill_price = 24500 * (1 + slippage_bps/10000)` and the order transitions to `FILLED`

#### Scenario: LIMIT BUY waits for cross

- **WHEN** a LIMIT BUY at 24400 is placed and ticks arrive at 24500, 24450, 24400, 24380
- **THEN** the order remains OPEN through 24500 and 24450, fills at the 24400 tick, and a single trade row is created

#### Scenario: SL triggers then fills

- **WHEN** an SL SELL with trigger 24300 is placed while LTP is 24400 and a tick at 24300 arrives
- **THEN** the order transitions to OPEN-triggered and fills at the next tick at the slipped market price

## Requirement: Order lifecycle

The system SHALL maintain orders through a strict state machine: `NEW → OPEN → (FILLED | CANCELLED | REJECTED)`. Cancellation SHALL be possible only from `NEW` or `OPEN`.

#### Scenario: Cancel open order

- **WHEN** `DELETE /api/v1/orders/{id}` is called on an OPEN order
- **THEN** the response is HTTP 200, the order status is `CANCELLED`, and a `cancelled_at` timestamp is set

#### Scenario: Reject invalid lot size

- **WHEN** an order is placed with `qty` not a multiple of the instrument's `lot_size`
- **THEN** the order is created with status `REJECTED` and `reject_reason = "qty not multiple of lot_size"`

## Requirement: Positions accounting

The system SHALL maintain a `positions` row per `(security_id, exchange_segment, product)` updated on every fill using weighted-average pricing for additions and realize-on-reduce semantics.

#### Scenario: Add and reduce

- **WHEN** BUY 50 @ 100 then BUY 50 @ 110 then SELL 50 @ 120 trades complete
- **THEN** the position has `net_qty = 50`, `avg_price = 105`, `realized_pnl = (120-105)*50 = 750`

## Requirement: Cost model applied per fill

The system SHALL compute charges (brokerage, STT, exchange fee, GST, SEBI charges, stamp duty) per fill using the `broker_costs` table keyed by `(broker, instrument_type)` and persist the total in `trades.charges`.

#### Scenario: Charges populated

- **WHEN** any paper trade fills for `instrument_type = OPTIDX`
- **THEN** `trades.charges > 0` and equals the sum from the broker_costs row for `(paper, OPTIDX)`

## Requirement: Mode gate header

The system SHALL include the header `X-Trade-Mode: PAPER` on every response from `/api/v1/orders*`, `/api/v1/positions`, and `/api/v1/trades` whenever the active broker is paper, and `X-Trade-Mode: LIVE` whenever live trading is active.

#### Scenario: Paper mode header

- **WHEN** `LIVE` env is unset (default) and any orders endpoint is hit
- **THEN** the response header `X-Trade-Mode: PAPER` is present

## Requirement: Order/trade/position event stream

The system SHALL expose a WebSocket `/ws/orders` that pushes JSON events `{type: "order"|"trade"|"position", payload: {...}}` whenever a corresponding row is inserted or updated.

#### Scenario: Trade event published

- **WHEN** a paper trade fills
- **THEN** every connected `/ws/orders` client receives `{"type":"trade","payload":{...}}` within 200ms

## Requirement: Live broker activation gate

The system SHALL activate the live Dhan broker only when `LIVE` is true AND `BROKER == "dhan"` AND Dhan credentials (`DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`) are configured. In every other case orders SHALL route to the paper engine. The default configuration SHALL be paper.

#### Scenario: Live activated with full configuration

- **WHEN** the app starts with `LIVE=1`, `BROKER=dhan`, and Dhan credentials set
- **THEN** a `DhanBroker` instance is started and registered with the `OrderRouter`
- **AND** order responses carry the header `X-Trade-Mode: LIVE`

#### Scenario: Missing credentials falls back to paper

- **WHEN** the app starts with `LIVE=1` and `BROKER=dhan` but `DHAN_CLIENT_ID` is empty
- **THEN** no `DhanBroker` is started and orders route to the paper engine with `X-Trade-Mode: PAPER`

## Requirement: Live order routing to Dhan

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

## Requirement: Dhan field and cost mapping

The system SHALL map platform order fields to Dhan SDK parameters: order type (`MARKET`→`MARKET`, `LIMIT`→`LIMIT`, `SL`→`STOP_LOSS`, `SL_M`→`STOP_LOSS_MARKET`), product (`NRML`→`MARGIN`, `MIS`→`INTRADAY`, `CNC`→`CNC`), and exchange segment (`NSE_CUR`→`NSE_CURRENCY`, others passed through). The `broker_costs` table SHALL contain rows for `broker = "dhan"` so charges are computed for live fills.

#### Scenario: SL order type mapped

- **WHEN** an order with `order_type = "SL"` and `product = "NRML"` is placed on Dhan
- **THEN** the Dhan request uses `order_type = "STOP_LOSS"` and `product_type = "MARGIN"`

#### Scenario: Live fill charges populated

- **WHEN** a live Dhan trade fills for `instrument_type = OPTIDX`
- **THEN** `trades.charges` is computed from the `broker_costs` row for `(dhan, OPTIDX)` and is greater than zero

## Requirement: Live fills from order-update stream

The system SHALL consume Dhan order-update events over the broker WebSocket. On an update with status `TRADED`, the system SHALL fetch the trade book for that broker order id, insert a `Trade` row, transition the `Order` to `FILLED`, upsert the `Position` using the same weighted-average / realize-on-reduce accounting as the paper engine, and publish the corresponding events to `/ws/orders`. Status `CANCELLED` and `REJECTED` SHALL transition the order accordingly.

#### Scenario: TRADED alert produces a fill

- **WHEN** an order-update event with status `TRADED` arrives for a known `broker_order_id`
- **THEN** the trade book is fetched, a `Trade` row is created with the broker fill price and quantity, the `Order` becomes `FILLED`, and the `Position` is updated
- **AND** `/ws/orders` clients receive `trade` and `position` events

#### Scenario: REJECTED alert transitions order

- **WHEN** an order-update event with status `REJECTED` arrives for a known `broker_order_id`
- **THEN** the `Order` transitions to `REJECTED` and a `/ws/orders` order event is published

## Requirement: Startup fill reconciliation

On startup the live broker SHALL reconcile orders that may have been filled or cancelled while the process was down, by fetching the broker order list and trade book and applying any fills not yet recorded locally.

#### Scenario: Missed fill recovered on startup

- **WHEN** the `DhanBroker` starts and an order that was `OPEN` locally is `TRADED` at the broker
- **THEN** the corresponding `Trade` and `Position` rows are created and the `Order` is transitioned to `FILLED` before live updates resume
