## 1. Schema

- [ ] 1.1 Alembic migration `0005_orders_trades_positions.py` for `orders`, `trades`, `positions`
- [ ] 1.2 Alembic migration `0006_broker_costs.py` for `broker_costs` + seed default `paper` rows for EQUITY / FUTIDX / OPTIDX / FUTSTK / OPTSTK
- [ ] 1.3 SQLAlchemy models in `src/pdp/orders/models.py`

## 2. Paper Engine

- [ ] 2.1 `src/pdp/orders/paper.py` — `PaperBroker` consuming Redis Pub/Sub `tick.<id>`
- [ ] 2.2 MARKET / LIMIT / SL / SL_M fill logic
- [ ] 2.3 Slippage from settings (`PAPER_SLIPPAGE_BPS`, default 2)
- [ ] 2.4 Position updater (weighted-avg + realize-on-reduce)
- [ ] 2.5 Charges calculator pulling from `broker_costs`

## 3. Order Router

- [ ] 3.1 `src/pdp/orders/router.py` — `OrderRouter.select_broker()` (paper in v1; live gate stub)
- [ ] 3.2 Idempotency on `client_order_id` UNIQUE
- [ ] 3.3 Lot-size validation against `instruments.lot_size`

## 4. API

- [ ] 4.1 `src/pdp/orders/routes.py` — `POST /api/v1/orders`, `GET /api/v1/orders`, `DELETE /api/v1/orders/{id}`
- [ ] 4.2 `GET /api/v1/positions`, `GET /api/v1/trades`
- [ ] 4.3 `X-Trade-Mode` header middleware
- [ ] 4.4 `src/pdp/orders/ws.py` — `/ws/orders` event stream

## 5. Tests

- [ ] 5.1 Unit: state machine transitions, idempotency, rejection on bad lot size
- [ ] 5.2 Unit: position math (add, reduce, flip)
- [ ] 5.3 Integration: place MARKET → inject tick → trade + position row appear
- [ ] 5.4 Integration: LIMIT order doesn't fill at non-crossing tick, fills at cross
- [ ] 5.5 Charges populated > 0 for OPTIDX paper trade

## 6. Validation

- [ ] 6.1 `openspec validate --strict add-paper-broker`
- [ ] 6.2 Manual smoke via `curl` after live tick feed is up: place MARKET on NIFTY future → see FILLED trade
