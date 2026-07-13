# mongo/ — MongoDB Client & Collection Init

Shared MongoDB client singleton and collection/index bootstrapping.

## Files

| File | Purpose |
|------|---------|
| `client.py` | `connect(settings) -> (client, db)` / `disconnect(client)` — Motor client with bounded pool + timeouts |
| `collections.py` | `ensure_indexes()` — creates all time-series collections + indexes on startup |

## Collections

| Collection | Type | Purpose |
|-----------|------|---------|
| `market_bars` | Time-series | Index 1m/5m/... OHLCV bars (NIFTY, BANKNIFTY, SENSEX, VIX) |
| `option_bars` | Time-series | Option contract 1m OHLCV bars |
| `option_chains` | Regular | Latest chain snapshot per underlying+expiry |
| `oi_snapshots` | Time-series | Intraday ATM±N OI snapshots + derived events (scripts/expiry_analysis.py --track) |
| `paper_journal` | Regular | Daily P&L journal (one doc per date) |
| `backtest_runs` | Regular | Backtest warehouse index — one doc per run; keys: `run_id`, `kind`, `metrics`, `verdict`, `promotion_state` |
| `backtest_days` | Regular | Per-day P&L rows keyed by `(run_id, date)` |
| `backtest_folds` | Regular | Walk-forward fold rows keyed by `(run_id, fold_index)` |
| `backtest_trades` | Regular | Fill-level trade rows keyed by `(run_id, date)` |
| `backtest_sweeps` | Regular | Sweep leaderboards: one doc per `sweep_id` with ranked combos + `best_param` |
| `backtest_decisions` | Regular | Strategy-agnostic why-entry/why-exit decision events, keyed by `(run_id, ts_ist, event)` |
| `backtest_promotions` | Regular | Audit log of PASS-gated promotions to paper strategies (evidence snapshot + optional note) |

## Usage

```python
from pdp.mongo.client import connect, disconnect
from pdp.settings import get_settings

client, db = connect(get_settings())
col = db["market_bars"]
# ... use col ...
disconnect(client)
```

## Note

MongoDB time-series collections **do not support upsert/update**.
Idempotent writes use **delete-then-insert** per day window (see `backfill_spot.py`).
