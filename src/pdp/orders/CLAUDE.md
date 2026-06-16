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

## Known Bug — Shared Position (UNFIXED as of 2026-06-16)

`PaperBroker` keys its in-memory position map by `security_id` only. When two strategies hold the **same** security (e.g. both st10_15m_otm3 and st10_5m_otm2_b3m7 sell CE24050), they share one position object. Effects:
- Heartbeat `lots` = inflated sum across strategies
- Stop-loss fires against the combined position → over-closes
- When strategy A flips and clears the shared position, strategy B sees `lots=0` and re-enters immediately (cascading re-entry)

**Fix**: Key `_positions` and the DB `positions` table by `(strategy_id, security_id)` instead of `security_id` alone. All callers that look up position by `security_id` must also pass `strategy_id`.

## Active Specs

`order-approval-center` (in-flight) — manual approval gate before live sends.
