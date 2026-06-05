## 1. Schema

- [x] 1.1 Add SQLAlchemy model `Instrument` in `src/pdp/instruments/models.py`
- [x] 1.2 Alembic migration `0002_instruments.py` with table + 2 indices
- [x] 1.3 `alembic upgrade head` confirms table created

## 2. Ingest

- [x] 2.1 `src/pdp/instruments/loader.py` — download CSV via httpx, parse with Polars
- [x] 2.2 Batched upsert helper using PG `ON CONFLICT`
- [x] 2.3 `pdp instruments refresh` CLI command wired in `pdp.cli`
- [x] 2.4 Settings: `DHAN_SCRIPMASTER_URL` (default to Dhan's public CDN URL)

## 3. API

- [x] 3.1 `src/pdp/instruments/service.py` — `search()`, `get_by_id()`
- [x] 3.2 `src/pdp/instruments/routes.py` — `/api/v1/instruments` + `/{security_id}`
- [x] 3.3 Register router in `pdp.main`

## 4. Tests

- [x] 4.1 `tests/test_instruments_loader.py` — fixture CSV (50 rows), upsert idempotency _(parse coverage; live upsert tested via integration once DB up)_
- [x] 4.2 `tests/test_instruments_api.py` — search by symbol, segment filter, 404 on missing

## 5. Validation

- [x] 5.1 `openspec validate --strict add-instrument-registry`
- [x] 5.2 Smoke: `pdp instruments refresh` populates real Dhan data, count > 100k _(193,659 rows; idempotent re-run preserved count)_
