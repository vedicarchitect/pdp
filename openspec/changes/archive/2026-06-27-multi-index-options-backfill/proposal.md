## Why

The directional-strangle backtest is NIFTY-only today. Extending it to BANKNIFTY or SENSEX requires option bars for those underlyings in `option_bars`. The spot backfill was already genericised (2026-06-26) — `backfill_spot.py` now accepts `--symbol NIFTY|BANKNIFTY|SENSEX` — but `backfill_options_gap.py` and its core library `gap_backfill.py` are still hardcoded to NIFTY (`UNDERLYING = "NIFTY"`, `UNDERLYING_SID = 13`, `STEP = 50`).

## What Changes

- **`src/pdp/options/gap_backfill.py`** — make `UNDERLYING`, `UNDERLYING_SID`, and `STEP` parameters to `backfill_gaps()` (and the internal helpers). Remove module-level hardcoded constants; callers supply them. Backward-compatible: callers that don't pass them get NIFTY defaults.
- **`scripts/backfill_options_gap.py`** — add `--symbol NIFTY|BANKNIFTY|SENSEX` (default `NIFTY`). Resolve the correct `underlying_sid`, `strike_step`, and `expiry_calendar_path` from a `SYMBOL_CONFIG` map. Pass all three down to `backfill_gaps()`.
- **Expiry calendar generalisation** — `NiftyExpiryCalendar` is NIFTY/Thursday-specific. BANKNIFTY expires on Thursday (same day, different contract); SENSEX is BSE Tuesday. Introduce a generic `ExpiryCalendar` base or a `SymbolExpiryCalendar.load(symbol, path)` factory so the correct calendar is loaded per symbol. Pre-built cache files for BANKNIFTY and SENSEX expire caches must be created (`data/expiry/banknifty_expiries.json`, `data/expiry/sensex_expiries.json`).
- **`Taskfile.yml`** — `backfill:options` keeps its NIFTY default; add `backfill:options:banknifty` and `backfill:options:sensex` convenience tasks (mirrors the spot task pattern).
- **Settings** — add `BANKNIFTY_EXPIRY_CACHE_PATH` and `SENSEX_EXPIRY_CACHE_PATH` to `settings.py`; fall back to `data/expiry/banknifty_expiries.json` and `data/expiry/sensex_expiries.json`.

## Capabilities

### Modified Capabilities
- `options-warehouse`: `option_bars` collection now stores multi-index bars (BANKNIFTY sid=25, SENSEX sid=51) in addition to NIFTY (sid=13). No schema change required — the existing `security_id` + `underlying` fields already disambiguate.

### Out of Scope
- Live BANKNIFTY/SENSEX warehouse subscription (separate change: `multi-index-warehouse`)
- BANKNIFTY/SENSEX strangle backtest (follows once data is available)

## Impact

- Modify `src/pdp/options/gap_backfill.py` (underlying/step params)
- Modify `scripts/backfill_options_gap.py` (--symbol flag, SYMBOL_CONFIG)
- Modify `src/pdp/instruments/expiry_calendar.py` (generalise or add factory)
- Modify `src/pdp/settings.py` (two new cache paths)
- Modify `Taskfile.yml` (two new tasks)
- Modify `scripts/CLAUDE.md` (table update)
- No new external dependencies; no new database tables or indexes
- Spot bars for BANKNIFTY/SENSEX must already exist (prerequisite: `backfill:banknifty`, `backfill:sensex`)
