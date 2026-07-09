# api-openapi-schema-completeness

**Minimal context set** (load only these when working this change):
- `proposal.md`, `design.md` (GOVERNANCE 5-phase), `tasks.md`, `specs/api-openapi-schema/spec.md`
- Backend: `backend/pdp/main.py` (`create_app` — `/docs`,`/redoc` already served), the routers in
  `orders/`, `portfolio/`, `risk/`, `journal/`, `positional/`, `broker_sync/`, `backtest/`,
  `events/`, `alerts/`, `strategy/`, `market/`, and new per-module `schemas.py`
- Reuses the request/response models from change #1 (`api-reliability-hardening`)

**Ship order:** after change #1 (needs its shared Pydantic models). Purely the response surface —
no business-logic change.
