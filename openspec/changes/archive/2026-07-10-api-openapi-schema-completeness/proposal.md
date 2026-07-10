# api-openapi-schema-completeness

## Why

The user asked whether we can add "a swagger kind of doc." FastAPI **already** serves interactive
Swagger UI at `/docs` and ReDoc at `/redoc` by default — `create_app()` in `backend/pdp/main.py`
sets no `docs_url`/`openapi_url`/`redoc_url` override (confirmed: 0 matches). So the tooling
exists; the gap is that the generated schema is nearly empty because ~90% of route handlers
return a bare `dict`/`JSONResponse` with **no `response_model=`** and often no explicit
`status_code=`. As a result `/docs` shows endpoints with no documented response shape, which
makes the docs untrustworthy for the Flutter client and for anyone integrating.

This change makes the auto-generated OpenAPI schema complete and typed, reusing the Pydantic
request/response models introduced in `api-reliability-hardening` so there is one model per
resource shape (DRY), not ad-hoc dicts.

## What Changes

- **Add `response_model=` + explicit `status_code=`** to route handlers that currently return
  bare dicts, across the routers (`orders`, `portfolio`, `risk`, `journal`, `positional`,
  `broker_sync`, `backtest/warehouse_routes`, `events`, `alerts`, `strategy`, `market`).
- **One response model per resource shape** in a per-module `schemas.py` (e.g.
  `orders/schemas.py`, `portfolio/schemas.py`), reused across list/detail endpoints — no
  duplicated inline shapes. List endpoints return a typed `Page[T]` wrapper aligned with the
  `PaginationParams` dependency from change #1.
- **Tag + summary hygiene** — every router keeps a stable `tags=[...]`; each mutating route gets
  a one-line `summary`/`description` so `/docs` reads as real documentation.
- **A schema-contract test** asserting `/openapi.json` declares a response schema (not empty) for
  every mutating route, so the docs cannot silently regress to bare dicts.

## Impact

- **Affected specs:** `api-openapi-schema` (new — the response-schema-completeness contract).
- **Affected code:** per-module `schemas.py` (new or extended) + `response_model=`/`status_code=`
  on the routers listed above. No business-logic change — purely the response surface.
- **Reuses:** the request/response Pydantic models from `api-reliability-hardening`; FastAPI's
  built-in OpenAPI generation and `/docs`/`/redoc` (no new tooling, no new dependency).
- **Flutter:** none required (response shapes are the same JSON, now merely typed in the schema);
  optionally the app team can regenerate models from `/openapi.json` later.
- **Depends on:** change #1 (`api-reliability-hardening`) for the shared models. Ship after #1.
