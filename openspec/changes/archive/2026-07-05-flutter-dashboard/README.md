# flutter-dashboard

**Minimal context set** (load only these when working this chunk):
- app/lib/features/portfolio/ (reference slice), app/lib/core/, app/lib/shared/
- backend market/portfolio/events REST+WS
- backend pdp/observability/routes.py — `GET /api/v1/analysis/session` for intraday session narrative; `GET /api/v1/observability/logs` for drill-down log panels
- app/lib/core/observability/log_shipper.dart — Flutter LogShipper (ship screen-level events)
