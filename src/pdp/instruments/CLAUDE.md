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
| `expiry_calendar.py` | `NiftyExpiryCalendar` — weekly/monthly expiry lookup |

## Key facts

- `security_id` is the Dhan internal ID (e.g. NIFTY index = `"13"`)
- Scrip master URL: `DHAN_SCRIPMASTER_URL` (set in `.env`)
- Expiry calendar loaded from `data/expiry/` JSON cache (`EXPIRY_CACHE_PATH` setting)
- `InstrumentLoader` runs on API startup if `DHAN_CLIENT_ID` is set

## Expiry calendar

```python
from pdp.instruments.expiry_calendar import NiftyExpiryCalendar
cal = NiftyExpiryCalendar.load(settings.EXPIRY_CACHE_PATH)
expiry = cal.next_weekly_expiry(date.today())
```
