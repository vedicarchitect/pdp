# Design — add-paper-broker

## State Machines

```
Order:   NEW ─► OPEN ─► FILLED
                 │         │
                 ├──► PARTIALLY_FILLED (disabled in v1; FILLED only)
                 ├──► CANCELLED
                 └──► REJECTED
```

## Schemas

```sql
CREATE TABLE orders (
    id              BIGSERIAL PRIMARY KEY,
    client_order_id TEXT UNIQUE,                  -- idempotency key from caller
    broker          TEXT NOT NULL,                -- 'paper' | 'dhan' | ...
    mode            TEXT NOT NULL,                -- 'PAPER' | 'LIVE'
    security_id     TEXT NOT NULL,
    exchange_segment TEXT NOT NULL,
    side            TEXT NOT NULL,                -- BUY | SELL
    qty             INTEGER NOT NULL,
    order_type      TEXT NOT NULL,                -- MARKET | LIMIT | SL | SL_M
    price           NUMERIC(14,4),
    trigger_price   NUMERIC(14,4),
    product         TEXT NOT NULL,                -- INTRADAY | DELIVERY | NRML | MIS
    status          TEXT NOT NULL,                -- NEW | OPEN | FILLED | CANCELLED | REJECTED
    placed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at       TIMESTAMPTZ,
    cancelled_at    TIMESTAMPTZ,
    reject_reason   TEXT,
    strategy_id     TEXT
);

CREATE TABLE trades (
    id              BIGSERIAL PRIMARY KEY,
    order_id        BIGINT NOT NULL REFERENCES orders(id),
    security_id     TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             INTEGER NOT NULL,
    fill_price      NUMERIC(14,4) NOT NULL,
    slippage_bps    NUMERIC(8,4) NOT NULL DEFAULT 0,
    charges         NUMERIC(12,4) NOT NULL DEFAULT 0,
    filled_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE positions (
    id              BIGSERIAL PRIMARY KEY,
    security_id     TEXT NOT NULL,
    exchange_segment TEXT NOT NULL,
    product         TEXT NOT NULL,
    net_qty         INTEGER NOT NULL DEFAULT 0,
    avg_price       NUMERIC(14,4) NOT NULL DEFAULT 0,
    realized_pnl    NUMERIC(14,4) NOT NULL DEFAULT 0,
    unrealized_pnl  NUMERIC(14,4) NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (security_id, exchange_segment, product)
);

CREATE TABLE broker_costs (
    broker             TEXT NOT NULL,
    instrument_type    TEXT NOT NULL,
    brokerage_bps      NUMERIC(8,4) NOT NULL DEFAULT 0,
    brokerage_flat     NUMERIC(8,4) NOT NULL DEFAULT 0,
    stt_bps            NUMERIC(8,4) NOT NULL DEFAULT 0,
    exchange_fee_bps   NUMERIC(8,4) NOT NULL DEFAULT 0,
    gst_pct            NUMERIC(8,4) NOT NULL DEFAULT 18,
    sebi_charges_bps   NUMERIC(8,4) NOT NULL DEFAULT 0,
    stamp_duty_bps     NUMERIC(8,4) NOT NULL DEFAULT 0,
    PRIMARY KEY (broker, instrument_type)
);
```

## Paper Fill Engine

- Subscribes to Redis Pub/Sub `tick.<id>` for each open order's security.
- MARKET buy → fills at next tick `ltp * (1 + slippage_bps/10000)`; sell → `ltp * (1 - slippage_bps/10000)`.
- LIMIT buy → fills when `ltp <= limit_price`; SELL when `ltp >= limit_price`.
- SL buy → trigger when `ltp >= trigger_price`, then convert to MARKET.
- Position math: weighted-avg on `net_qty != 0` add; realize-on-reduce.

## Mode Gate

```python
def select_broker(settings: Settings) -> str:
    if settings.LIVE and settings.BROKER == "dhan" and dhan_credentials_present():
        return "dhan"
    return "paper"
```

Every response includes `X-Trade-Mode` header populated from the active broker.
