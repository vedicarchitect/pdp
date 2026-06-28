# trade-analysis-feedback-loop

Unified OpenSearch log pipeline: every backend + Flutter UI log auto-ships to OpenSearch in
realtime through one path, segregated by `source`; typed analytics indices + dashboards
power the trade-analysis feedback loop. Supersedes the flat-file export.

**Minimal context set** (load only these when working this chunk):
- `backend/pdp/observability/` (new module — the pipeline)
- `backend/pdp/logging.py` (structlog chain — processor wires in here)
- Source emit sites: `backend/pdp/strategy/log.py`, `backend/pdp/journal/service.py`, `backend/pdp/backtest/store.py`
- `backend/pdp/settings.py`, `backend/pdp/main.py` (settings + lifespan wiring)
- `infra/compose/docker-compose.yml`, `infra/opensearch/dashboards/` (infra + dashboards-as-code)
- `app/` log bootstrap (Flutter `LogShipper`)
- Depends on `strangle-execution-console` (canonical strangle events)
