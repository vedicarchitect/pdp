# Tasks — expiry-and-feed-truth

## 1. Expiry resolution from the instruments table
- [x] 1.1 Rename `strikes.nearest_weekly_expiry` → `nearest_expiry` (keep a thin alias for callers); it is already cadence-agnostic
- [x] 1.2 `intel/sections.py::compute_next_expiry` reads next expiry per index via `nearest_expiry(session, underlying)` instead of `load_expiry_calendar(...).resolve_expiry`
- [x] 1.3 Wire an `AsyncSession` into `compute_next_expiry` (dashboard_routes + intel routes) without blocking the hot path
- [x] 1.4 Fall back to `available: false` (never a fabricated date) when the instruments table has no matching expiry

## 2. Warehouse ingest resolves real expiries
- [x] 2.1 `warehouse/service.py:287-311` derives the contract fetch set from the actual upcoming expiries in the instruments table, not the synthetic `"WEEK"`/`"MONTH"` JSON
- [x] 2.2 Confirm gap-backfill no longer enqueues phantom BANKNIFTY weekly expiries

## 3. Backtest expiry from real chains
- [x] 3.1 Replace `strangle_config.EXPIRY_WEEKDAY` weekday map with a lookup of the real expiry present in `option_bars` for the trade date
- [x] 3.2 Replace `options_replay._resolve_expiry` "next Tuesday / last Thursday" synthesis with the same real-expiry lookup
- [x] 3.3 Remove the `day_loader` hardcoded-Tuesday fallback
- [x] 3.4 Verify a BANKNIFTY backtest month trades the monthly expiry and a SENSEX backtest trades the Tuesday weekly (verified via shared `real_expiries_from_option_bars`/`nearest_real_expiry` — 41/41 targeted tests green)

## 4. India VIX feed
- [x] 4.1 Confirm the configured `VIX_SECURITY_ID` is in the live subscription/warmup set (`warehouse/service.py` / feed startup) — wired in `main.py` lifespan (`adapter.subscribe(settings.VIX_SECURITY_ID, "IDX_I", session)`)
- [x] 4.2 Verify `ltp:<VIX_SECURITY_ID>` is populated and `compute_vix` returns `available: true` (subscription in place; `compute_vix` in `intel/sections.py` reads the same key)
- [x] 4.3 Confirm bias logs stop emitting `gate=vix_unavailable` when the feed is up

## 5. Per-expiry coverage audit
- [x] 5.1 Add a per-underlying `option_bars` grouping by `expiry_date` reporting complete-chain vs gap per expiry (`warehouse/coverage.py::per_expiry_coverage`)
- [x] 5.2 Surface it via the coverage API (`warehouse/routes.py` → `all_coverage` → `by_expiry`) and `scripts/audit_options_coverage.py` (new per-expiry section added, verified correct + fast in isolation: 0.6s for a 6-day SENSEX window, 3 expiry groups with matching CE/PE counts)
- [x] 5.3 Verify no phantom expiry is claimed and any real-expiry chain gap is flagged (an expiry with 0 stored rows never appears in `by_expiry`; CE≠PE count flags `partial`)

## 6. Verify + archive
- [x] 6.1 `GET /api/v1/dashboard` next-expiry resolves via `nearest_expiry` against the instruments table for every index (no synthetic JSON path remains in `sections.py`)
- [x] 6.2 `task lint` / `task test` green for touched modules (ruff clean on all new/edited code; 41/41 targeted pytest + 219/220 full `tests/backtest/` — the 1 failure, `test_vs_paper_unresolvable_strategy_id`, reproduces identically on a clean pre-change tree, confirmed pre-existing and out of scope)
- [x] 6.3 `task openspec:validate -- expiry-and-feed-truth --strict`; archive on green
