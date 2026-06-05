## ADDED Requirements

### Requirement: Order placement endpoint

The system SHALL expose `POST /api/v1/orders` accepting `{client_order_id, security_id, exchange_segment, side, qty, order_type, price?, trigger_price?, product, strategy_id?}` and persisting a new order row with status `NEW`.

#### Scenario: Successful placement

- **WHEN** `POST /api/v1/orders` is called with a valid MARKET order body and unique `client_order_id`
- **THEN** the response is HTTP 201 with the created order, status `OPEN`, broker `paper`
- **AND** the response header `X-Trade-Mode: PAPER` is present

#### Scenario: Idempotent placement

- **WHEN** the same `client_order_id` is submitted twice
- **THEN** the second response returns the original order with HTTP 200 (not duplicated)

### Requirement: Deterministic paper fills

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

### Requirement: Order lifecycle

The system SHALL maintain orders through a strict state machine: `NEW → OPEN → (FILLED | CANCELLED | REJECTED)`. Cancellation SHALL be possible only from `NEW` or `OPEN`.

#### Scenario: Cancel open order

- **WHEN** `DELETE /api/v1/orders/{id}` is called on an OPEN order
- **THEN** the response is HTTP 200, the order status is `CANCELLED`, and a `cancelled_at` timestamp is set

#### Scenario: Reject invalid lot size

- **WHEN** an order is placed with `qty` not a multiple of the instrument's `lot_size`
- **THEN** the order is created with status `REJECTED` and `reject_reason = "qty not multiple of lot_size"`

### Requirement: Positions accounting

The system SHALL maintain a `positions` row per `(security_id, exchange_segment, product)` updated on every fill using weighted-average pricing for additions and realize-on-reduce semantics.

#### Scenario: Add and reduce

- **WHEN** BUY 50 @ 100 then BUY 50 @ 110 then SELL 50 @ 120 trades complete
- **THEN** the position has `net_qty = 50`, `avg_price = 105`, `realized_pnl = (120-105)*50 = 750`

### Requirement: Cost model applied per fill

The system SHALL compute charges (brokerage, STT, exchange fee, GST, SEBI charges, stamp duty) per fill using the `broker_costs` table keyed by `(broker, instrument_type)` and persist the total in `trades.charges`.

#### Scenario: Charges populated

- **WHEN** any paper trade fills for `instrument_type = OPTIDX`
- **THEN** `trades.charges > 0` and equals the sum from the broker_costs row for `(paper, OPTIDX)`

### Requirement: Mode gate header

The system SHALL include the header `X-Trade-Mode: PAPER` on every response from `/api/v1/orders*`, `/api/v1/positions`, and `/api/v1/trades` whenever the active broker is paper, and `X-Trade-Mode: LIVE` whenever live trading is active.

#### Scenario: Paper mode header

- **WHEN** `LIVE` env is unset (default) and any orders endpoint is hit
- **THEN** the response header `X-Trade-Mode: PAPER` is present

### Requirement: Order/trade/position event stream

The system SHALL expose a WebSocket `/ws/orders` that pushes JSON events `{type: "order"|"trade"|"position", payload: {...}}` whenever a corresponding row is inserted or updated.

#### Scenario: Trade event published

- **WHEN** a paper trade fills
- **THEN** every connected `/ws/orders` client receives `{"type":"trade","payload":{...}}` within 200ms
