# instruments/ — Dhan Instrument Registry

Dhan scrip master loader, NSE/BSE/MCX instrument metadata, expiry calendar.

## Files

| File | Purpose |
|------|---------|
| `loader.py` | `InstrumentLoader` — fetches Dhan scrip master CSV, upserts to PG |
| `service.py` | `InstrumentService` — search, lookup by security_id/symbol |
| `models.py` | `Instrument` ORM model |
| `schemas.py` | Pydantic response schemas |
| `routes.py` | FastAPI router (`/api/v1/instruments`) |
| `symbols.py` | Symbol normalisation helpers (NSE, BSE, MCX) |
| `snapshots.py` | Daily snapshot diffing for instrument changes |
| `expiry_calendar.py` | `NiftyExpiryCalendar` — weekly/monthly expiry lookup; also `load_expiry_calendar_from_db`/`record_confirmed_expiry` for the Mongo-backed calendar (see below) |

## Key facts

- `security_id` is the Dhan internal ID (e.g. NIFTY index = `"13"`)
- Scrip master URL: `DHAN_SCRIPMASTER_URL` (set in `.env`)
- `InstrumentLoader` does **not** run on API/engine startup. It's driven by
  `ScripRefreshScheduler` (`pdp/instruments/scheduler.py`, started in `OpsGroup` —
  `pdp/runtime/groups.py`, role `ops`/`all`) on its own schedule, or manually via
  `scripts/snapshot_instruments.py`.

## Expiry calendar (`option-bars-expiry-gap-backfill`, 2026-07-17)

The **persistent, editable source of truth** is now the Mongo `expiry_calendar` collection — one
doc per `(underlying, flag, expiry_date)` — not the `data/expiry/` JSON cache, because the JSON
cache derives expiries by walking `option_bars` for a chain, which is blind to a day where the
chain itself never got backfilled (a confirmed gap day silently produces a wrong/missing expiry).
`scripts/seed_expiry_calendar.py` / `scripts/seed_expiry_from_bhavcopy.py` seed it from NSE/BSE
bhavcopy archives (weekday + lot size per row, 1257 docs across NIFTY/BANKNIFTY/SENSEX at last
seed). Use `load_expiry_calendar_from_db(mdb, underlying)` to build a `NiftyExpiryCalendar` from
it; `record_confirmed_expiry` upserts one-off confirmed dates. The old JSON-cache path
(`NiftyExpiryCalendar.load(cache_path)`) still exists for callers that haven't migrated.

```python
from pdp.instruments.expiry_calendar import load_expiry_calendar_from_db
cal = load_expiry_calendar_from_db(mdb, "NIFTY")
expiry = cal.next_weekly_expiry(date.today())
```
