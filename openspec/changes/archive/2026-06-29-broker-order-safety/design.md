## Context

`OrderRouter.place_order()` is the single entrypoint for all order placement (paper and live).
Today it routes straight to `PaperBroker.place()` or `DhanBroker.place()` with no checks in
between. `DhanBroker` uses the synchronous `dhanhq` SDK wrapped in a thread; `broker_sync/client.py`
already fetches fund limits and demonstrates the credential-gated, SDK-envelope-unwrapping pattern
(`{"status","remarks","data"}`). Charges already exist twice: a full backtest model
(`backtest/commissions.py`) and a live post-fill `ChargesCalculator` (`orders/paper.py`) backed by
the `broker_costs` table. Lot size is loaded into `Instrument.lot_size` from the Dhan scrip master
but never validated at order time; freeze quantity is not captured at all.

OpenAlgo reference (`openalgo/broker/dhan/api/margin_api.py`): `_normalise_success_response()`
converts an HTTP-200 error payload to a failure; `calculate_margin_api()` routes 1 position to
`/margincalculator` and 2+ to `/margincalculator/multi`; `parse_basket_margin_response()` accepts
both snake_case and camelCase keys. A straddle/strangle basket margin is materially lower (~40%)
than the naive per-leg sum, so the basket route matters for correct sizing.

## Goals / Non-Goals

**Goals:**
- One preflight gate, run by `OrderRouter` before any live send, that returns a structured result:
  `{ok, margin_required, margin_available, charge_estimate, violations[]}`.
- Live: a hard failure (insufficient margin, bad lot/freeze) blocks the send. Paper: advisory only —
  result is logged and attached, never blocks.
- Margin via the real Dhan API, read-only, credential-gated — usable even in paper mode for sizing.
- Reuse existing `ChargesCalculator` and `BrokerFund`; no duplicate cost or funds logic.

**Non-Goals:**
- SPAN/exposure margin modelling locally — defer to the broker's number.
- Per-strategy capital allocation or portfolio-level margin budgeting (future risk-module work).
- Caching/throttling the margin endpoint beyond a single call per placement (basket = one call).
- Changing fill-time charging behaviour.

## Decisions

### D1 — Preflight lives in `OrderRouter`, not in each broker
A single `_preflight(orders)` step in `OrderRouter.place_order()` keeps the "never bypass the
router" invariant and means paper and live share the same checks. `MarginService` is injected
(like `dhan_broker`) and is `None` when uncredentialed.

### D2 — Basket vs single routing by leg count
A strangle entry submits its legs together; `MarginService.required_margin(orders)` routes
`len==1 → /margincalculator`, `len>=2 → /margincalculator/multi`. Callers that place one leg at a
time still get a (single-leg) check.

### D3 — HTTP-200-error guard is mandatory for the margin endpoint
`_normalise_success_response(resp)` raises/flags when a 200 body has `status=="failure"` or an
`errorType`/`errorMessage`. Without it a Dhan validation error reads as "0 margin required" and
would wrongly pass.

### D4 — `freeze_qty` sourced from the scrip master, settings fallback
Add an `instruments.freeze_qty` column populated by the loader when the master carries it. If a
row lacks it, fall back to a per-underlying `FREEZE_QTY_BY_UNDERLYING` settings map so validation
still works for NIFTY/BANKNIFTY/SENSEX from day one.

### D5 — Gating
`ORDER_PREFLIGHT_ENABLED` (default True) governs lot/freeze + charge estimate (no network).
`MARGIN_CHECK_ENABLED` additionally requires Dhan creds; with no creds the margin portion is
skipped with a `margin_check_skipped` advisory and the rest of preflight still runs.

## Failure Modes

- **No creds** → margin skipped, advisory logged, lot/freeze + charges still enforced.
- **Margin endpoint 200-with-error** → caught by D3, treated as a preflight failure (live blocks).
- **Margin API timeout/exception** → in live, fail-closed (block) by default; configurable to
  fail-open via `MARGIN_FAILOPEN` for owners who accept the risk. Paper always proceeds.
- **`freeze_qty` unknown for a symbol** → settings-map fallback; if still unknown, skip the freeze
  check with a one-time warning (never block on missing reference data).

## Open Questions

- Exact Dhan basket-margin field names per current SDK version — resolve against the live response
  during the owner paper run (parser already accepts both cases).
