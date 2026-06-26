# mongo/ — MongoDB Client & Collection Init

Shared MongoDB client singleton and collection/index bootstrapping.

## Files

| File | Purpose |
|------|---------|
| `client.py` | `get_mongo_client()` — singleton `MongoClient` via settings |
| `collections.py` | `ensure_indexes()` — creates all time-series collections + indexes on startup |

## Collections

| Collection | Type | Purpose |
|-----------|------|---------|
| `market_bars` | Time-series | Index 1m/5m/... OHLCV bars (NIFTY, BANKNIFTY, SENSEX, VIX) |
| `option_bars` | Time-series | Option contract 1m OHLCV bars |
| `option_chains` | Regular | Latest chain snapshot per underlying+expiry |
| `oi_snapshots` | Time-series | Intraday ATM±N OI snapshots + derived events (scripts/expiry_analysis.py --track) |
| `paper_journal` | Regular | Daily P&L journal (one doc per date) |

## Usage

```python
from pdp.mongo.client import get_mongo_client
from pdp.settings import get_settings

client = get_mongo_client()
db = client[get_settings().MONGO_DB_NAME]
col = db["market_bars"]
```

## Note

MongoDB time-series collections **do not support upsert/update**.
Idempotent writes use **delete-then-insert** per day window (see `backfill_spot.py`).
