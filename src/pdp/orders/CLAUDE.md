# Orders Module

## Files

| File | Size | Role |
|------|------|------|
| `paper.py` | 15.5 KB | `PaperBroker` — always running; simulates fills from Redis LTP; slippage via `PAPER_SLIPPAGE_BPS` |
| `dhan_broker.py` | 16.6 KB | `DhanBroker` — live-gated (`LIVE=1` + creds); sends real orders to Dhan API |
| `router.py` | 6.9 KB | `OrderRouter` — routes to paper or live based on settings; single entry point for all order placement |
| `models.py` | 5.4 KB | SQLAlchemy models: `Order`, `Trade`, `Position` (PostgreSQL) |
| `routes.py` | 6.6 KB | REST endpoints: place, cancel, list orders; query positions/trades |
| `ws.py` | 3.4 KB | `OrdersHub` + WS router — broadcasts fill events to connected clients |

## Order Routing Logic

```
OrderRouter.place_order(req)
  → if LIVE=1 AND BROKER=dhan AND dhan_broker is not None:
      DhanBroker.place()   # real money
  → else:
      PaperBroker.place()  # always safe default
```

**Never bypass `OrderRouter`** — strategies and API routes must use it exclusively.

## PaperBroker Key Behaviour

- Gets LTP from Redis key `ltp:<security_id>` (TTL 5s, set by TickRouter).
- Applies `PAPER_SLIPPAGE_BPS` (default 2bps) to fill price.
- Persists fills to PostgreSQL `orders` + `trades` tables.
- Broadcasts fills via `OrdersHub` → `PortfolioService` + `JournalService`.

## Adding a New Broker

1. Create `<name>_broker.py` implementing `BaseBroker` (see `paper.py` for interface).
2. Add instantiation in `main.py` lifespan (mirror the dhan_broker block).
3. Wire into `OrderRouter.__init__()`.
4. Add `BROKER` literal to `settings.py`.

## Shared Position Bug — FIXED 2026-06-18

`Position` rows are now keyed by `(strategy_id, security_id, exchange_segment, product)`.

- `upsert_position()` in `paper.py` and `dhan_broker.py` sets and queries `strategy_id`.
- `StrategyContext` position queries (`get_net_qty`, `get_position`, `get_realized_pnl`, `get_positions`) all filter by `strategy_id`.
- `PortfolioService` cache key is now `(strategy_id, security_id, exchange_segment, product)`.
- Migration `0012` adds the column and rekeyed unique constraint.
- Run `task db:migrate` after pulling to apply the migration.

## Active Specs

`order-approval-center` (in-flight) — manual approval gate before live sends.
