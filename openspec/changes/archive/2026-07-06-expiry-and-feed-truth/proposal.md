# expiry-and-feed-truth

## Why

The dashboard shows wrong next-expiry dates because it reads **synthetic, forward-projected
JSON calendars** instead of the real tradeable instruments. `compute_next_expiry`
(`pdp/intel/sections.py:97-110`) calls `load_expiry_calendar(...).resolve_expiry(today,
"WEEK", 1)` for all three indices against `data/expiry/{banknifty,sensex}_expiries.json`,
whose `"WEEK"` arrays are algorithmically extended to 2030 on obsolete weekday cadences.
The result: BANKNIFTY shows a weekly `2026-07-08` even though BANKNIFTY is monthly-only now,
and SENSEX shows Thursday `2026-07-09` even though BSE SENSEX is Tuesday-weekly.

A correct source already exists and is unused by the dashboard: `strikes.py:55-67`
(`nearest_weekly_expiry`) resolves `SELECT min(expiry) FROM instruments WHERE
underlying=? AND option_type IN (CE,PE) AND expiry>=?` — cadence-agnostic, driven by the
Dhan scrip master. The live strangle already uses this path, so live trading is not misled —
only the dashboard and the warehouse ingest feed (`warehouse/service.py:287-311`, which
picks contracts via the same stale `"WEEK"` JSON) are.

Two adjacent truth gaps ride along, because they block trusting the same dashboard: **India
VIX shows "Unavailable"** (the bias engine's `vix_gate` then suppresses entries vs the
backtest), and **option-chain coverage is validated per trading-day but never per expiry**,
so a phantom expiry (or a real expiry with a missing chain) is never surfaced.

MCX commodity tiles also show "Unavailable" but are **explicitly out of scope this pass**
(deferred by the owner).

## What Changes

- **Next-expiry resolves from the instruments table, not the JSON cache.** `compute_next_expiry`
  reads the real next expiry per index via the instruments-table query (reuse
  `strikes.nearest_weekly_expiry`, renamed `nearest_expiry` since it is cadence-agnostic).
  The dashboard and `/api/v1/intel/next-expiry` return the true next expiry for each of
  NIFTY (weekly), BANKNIFTY (monthly), SENSEX (weekly-Tuesday).
- **Warehouse ingest resolves contracts from real expiries.** `warehouse/service.py` stops
  deriving the fetch set from the synthetic `"WEEK"`/`"MONTH"` JSON and uses the actual
  upcoming expiries present in the instruments table, so gap-backfill no longer chases
  phantom BANKNIFTY weeklies.
- **Backtest expiry resolution uses real expiries.** The backtest's hardcoded weekday math
  (`strangle_config.EXPIRY_WEEKDAY`, `options_replay._resolve_expiry`, `day_loader` Tuesday
  fallback) is replaced by the actual expiry present in `option_bars` for the trade date —
  fixing BANKNIFTY-monthly / SENSEX-Tuesday backtest realism.
- **India VIX is fed and served.** The configured VIX security id is subscribed/warmed so
  `ltp:<VIX_SECURITY_ID>` is populated; the dashboard VIX section and the bias `vix_gate`
  see a real value instead of "Unavailable".
- **Per-expiry coverage audit.** A new coverage view groups `option_bars` by `expiry_date`
  per underlying and reports, for each claimed expiry, whether a complete chain exists or a
  gap — closing the phantom-expiry / missing-chain blind spot.

## Impact

- Affected specs: `nifty-expiry-calendar` (resolution source becomes the instruments table),
  `dashboard-market-feeds` (next-expiry source; VIX availability), `market-data-coverage`
  (per-expiry coverage requirement).
- Affected code: `backend/pdp/intel/sections.py`, `backend/pdp/strategy/strikes.py`,
  `backend/pdp/warehouse/service.py`, `backend/pdp/warehouse/coverage.py`,
  `backend/pdp/backtest/{strangle_config.py, options_replay.py, day_loader.py}`,
  `backend/scripts/audit_options_coverage.py`, VIX subscription wiring in
  `backend/pdp/warehouse/service.py` / feed startup.
- Reuses `strikes.nearest_weekly_expiry` (the correct query), the `Instrument` model, and
  the existing coverage aggregation scaffolding. No new pivot/expiry math — this rewires
  readers to the real source and adds a per-expiry grouping.
- Out of scope (deferred): MCX commodity feed; the synthetic `data/expiry/*.json` files may
  remain on disk but are no longer the source of truth for next-expiry.
