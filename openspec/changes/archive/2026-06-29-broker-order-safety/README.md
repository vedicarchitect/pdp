# broker-order-safety

**Minimal context set** (load only these when working this chunk):
- backend/pdp/orders/ (router.py, paper.py, dhan_broker.py, models.py) + new margin.py
- backend/pdp/instruments/ (models.py, loader.py)
- backend/pdp/broker_sync/client.py (fetch_funds), backend/pdp/settings.py
- reference: openalgo/broker/dhan/api/margin_api.py (single/basket routing, 200-error guard)
