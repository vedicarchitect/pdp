# journal/ — Trade Journal & Daily Stats

Records fills, computes daily P&L stats, and persists paper-trading journal entries to MongoDB.

## Files

| File | Purpose |
|------|---------|
| `service.py` | `JournalService` — listens for fills, writes `paper_journal` documents |
| `stats.py` | `DailyStats` computation (round-trips, wins/losses, gross premium) |
| `routes.py` | FastAPI router (`/api/v1/journal`) |

## MongoDB collection

`paper_journal` — one document per IST trade date:
```json
{
  "date": "2026-06-14",
  "stats": {
    "round_trips": 3,
    "wins": 2,
    "losses": 1,
    "realized_pnl": 4200.0,
    "gross_premium_sold": 18000.0,
    "gross_premium_bought": 13800.0
  },
  "fills": [...]
}
```

## Usage

`JournalService` is started automatically during API lifespan.
It subscribes to the `orders.filled` event from `OrderRouter`.
Backtest-vs-paper comparison reads realized P&L from the PostgreSQL `trades`/`orders` ledger
(`pdp.backtest.paper_compare`), not this Mongo journal — see `GET /runs/{id}/vs-paper`.
