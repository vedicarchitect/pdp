# market-feed-resilience

**Minimal context set** (load only these when working this chunk):
- backend/pdp/market/ (dhan_ws.py, router.py)
- backend/pdp/options/gap_backfill.py
- backend/pdp/instruments/ (loader.py, snapshots.py)
- backend/pdp/broker_sync/scheduler.py (scheduling reference), backend/pdp/settings.py
- reference: openalgo/broker/dhan/api/data.py (interior-gap detection)
