# Tasks — api-openapi-schema-completeness

## 1. Shared response schemas
- [x] 1.1 Add generic `Page[T]` wrapper in `pdp/schemas.py`
- [x] 1.2 Per-module `schemas.py` response models (`OrderOut`, `BrokerPositionOut`, `JournalDayOut`,
      `AlertOut`, `StrategyActionOut`, `HousekeepingOut`, …) — one model per resource shape, reused

## 2. Annotate routers
- [x] 2.1 `response_model=` + `status_code=` on `orders`, `portfolio`, `risk`, `journal`,
      `positional`, `broker_sync`, `backtest/warehouse_routes`, `events`, `alerts`, `strategy`,
      `market`, `jobs`, `ml`, `options`, `housekeeping`
- [x] 2.2 List endpoints return `Page[T]` aligned with `PaginationParams` (broker_sync, alerts, …)
- [x] 2.3 `summary`/`description` on mutating routes; stable `tags=[...]`
- [x] 2.4 Status-code hygiene: create→201, action→200/202, delete→204

## 3. Regression guard + validation
- [x] 3.1 `tests/test_openapi_contract.py` asserts every `/api` 2xx route has a typed
      `application/json` schema (fails on any bare-dict route) — passes
- [x] 3.2 `/docs` (Swagger) + `/redoc` render the populated schema (default FastAPI mounts)
- [x] 3.3 `task test` green for the contract test
- [x] 3.4 `openspec validate --strict api-openapi-schema-completeness` passes
