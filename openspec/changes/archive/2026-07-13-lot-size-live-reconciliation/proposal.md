# lot-size-live-reconciliation

## Why

Exchange lot sizes for index options change periodically (SEBI minimum-contract-value reviews,
index-level rebalancing) — NIFTY alone has moved 75→50→25→75→65 since 2021 per
`pdp/backtest/strangle_config.py:_LOT_HISTORY`. Backtest already handles this correctly:
`lot_size_for_date(underlying, trade_date)` resolves the period-correct lot size per historical
day from a maintained table.

Live/paper does not. `DirectionalStrangle.__init__` (`directional_strangle.py:174`) reads a
**static** `lot_size` out of the strategy's YAML config once at construction and caches it in
`self._lot_size` for the life of the process. That number is set by a human editing
`strategies/directional_strangle_{nifty,banknifty,sensex}.yaml` when they happen to notice an NSE/
BSE circular — the comments literally say "Jan 2026+ NIFTY lot size", "2025+ BANKNIFTY lot size",
i.e. someone tracking this by hand.

Meanwhile the actual authoritative value already exists in this codebase, refreshed automatically:
`InstrumentLoader` fetches the Dhan scrip master on API startup and upserts it into the
`instruments` table, and `Instrument.lot_size` (`pdp/instruments/models.py:30`) carries the real,
current, exchange-mandated lot size for every option row. `strikes.resolve_otm_option()` already
resolves an `Instrument` for the underlying on every entry — the correct number is one query away
and is never used for sizing.

The only thing that currently notices a YAML/reality mismatch is the order router
(`pdp/orders/router.py:289`), which validates `qty % Instrument.lot_size == 0` against the real
scrip master before accepting an order and **rejects** on mismatch. That's a safety net, not a
fix: it fails closed (no bad-sized trade goes out) but fails **silently** — a stale YAML value
after a lot-size change quietly stops the strategy from entering new positions, with no operator
signal beyond an order-reject log line nobody is necessarily watching.

## What Changes

- **Resolve lot size from the live scrip master, not YAML.** New helper (in `strikes.py` or
  `pdp/instruments/service.py`) queries the `instruments` table for the underlying's current
  option lot size. `DirectionalStrangle` calls it once per IST trading day (at session start, not
  per-bar — this is a daily-cadence fact, not a hot-path lookup) and caches the result for that
  day as `self._lot_size`.
- **YAML `lot_size` becomes optional and advisory only.** If present, it is compared against the
  resolved value at session start; a mismatch logs a `WARNING` (and emits an event, so it's
  visible on the dashboard/alerts feed) but the **resolved value always wins** for sizing. YAML is
  never authoritative again.
- **Fail closed and loud when unresolvable.** If the `instruments` table has no option row for the
  underlying at session start (loader never ran, table empty, underlying misconfigured), the
  strategy SHALL NOT fall back to a hardcoded default (today's `65`) and SHALL NOT silently place
  orders. It marks itself degraded for new entries on that underlying and surfaces an alert.
  Existing open legs still use the last known-good lot size for exit/MTM accounting so nothing is
  stranded.
- **Order router validation is unchanged** — it remains the final defense-in-depth check; this
  change removes the *reason* it would ever fire in normal operation, it doesn't replace it.
- **Backtest is out of scope.** `strangle_config.lot_size_for_date()` is already correct and must
  stay as-is — the live scrip master only reflects currently active contracts, so historical
  backtest dates cannot use this same live-lookup mechanism.

## Impact

- **Affected specs:** `lot-size-live-reconciliation` (new).
- **Affected code:** `backend/pdp/strategies/directional_strangle.py` (lot-size resolution +
  caching), `backend/pdp/strategy/strikes.py` (new lookup helper), the three
  `strategies/directional_strangle_*.yaml` configs (`lot_size` becomes optional/commented as
  advisory), `backend/pdp/strategy/CLAUDE.md`.
- **Not affected:** `pdp/backtest/strangle_config.py`, `pdp/orders/router.py` (behavior preserved,
  just expected to fire far less often).
- **No data migration.**
- **Operational dependency:** correctness depends on `InstrumentLoader` having run recently enough
  that the `instruments` table reflects the current lot size before a trading day starts — this
  change does not add scheduling for that; it assumes the existing startup load is fresh. If that
  assumption turns out false in practice, a periodic intraday refresh is a candidate follow-up, not
  part of this change's scope.
