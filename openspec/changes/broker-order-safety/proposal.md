## Why

PDP places live orders through `OrderRouter` with no pre-trade safety net. A directional
strangle is a multi-leg basket: today each leg is sent on its own, so Dhan can accept the first
short and then reject the hedge for insufficient margin, leaving a naked position. There is also
no check that order quantity is a valid lot multiple or within the exchange freeze limit, and
charges are only computed *after* a fill — never surfaced before placement.

OpenAlgo's Dhan adapter (reference implementation) solves exactly these with a margin pre-check
that routes single vs basket orders, a `_normalise_success_response` guard (Dhan returns errors
with **HTTP 200** on the margin endpoint), and lot/freeze validation at order time. This change
ports those patterns into PDP, paper-first and credential-gated.

## What Changes

- **Pre-flight margin check** — new `MarginService` (`backend/pdp/orders/margin.py`) calling
  Dhan's margin API: single leg → `/margincalculator`, basket of 2+ legs → `/margincalculator/multi`.
  Read-only and credential-gated (skips with a logged advisory when no creds, like `broker_sync`).
  Required margin is compared against available funds (`BrokerFund.available_balance`, already
  fetched by `broker_sync/client.py`).
- **Dhan HTTP-200-error guard** — a `_normalise_success_response` helper so a 200 response
  carrying an error payload is treated as a failure (Dhan's margin endpoint does this), with
  dual snake_case/camelCase response parsing.
- **Pre-trade charge estimate** — reuse the existing `ChargesCalculator` (`backend/pdp/orders/paper.py`,
  reading the `broker_costs` table) to attach an estimated cost breakdown to the preflight result
  *before* the order is sent.
- **Lot-size + freeze-quantity validation** — reject orders whose qty is not a whole lot multiple
  or exceeds the exchange freeze limit, using `Instrument.lot_size` (and a new `freeze_qty`).

## Capabilities

### New Capabilities
- `order-preflight`: a paper-first, advisory-in-paper / blocking-in-live pre-trade gate run by
  `OrderRouter` before any live send — margin adequacy, lot/freeze validation, and a charge
  estimate, exposed on the order response.

### Modified Capabilities
_(none — `order-execution` is extended via `OrderRouter`; existing routes are unchanged)_

## Impact

- **`backend/pdp/orders/margin.py`** (new): `MarginService` — single/basket Dhan margin calls,
  `_normalise_success_response`, dual-case response parsing.
- **`backend/pdp/orders/router.py`**: run preflight before the live `DhanBroker.place()` branch;
  block on hard failure in live, attach advisory result in paper. Never bypassed.
- **`backend/pdp/orders/paper.py`**: expose `ChargesCalculator` for pre-trade estimation (no
  behaviour change to fill-time charging).
- **`backend/pdp/orders/models.py`**: preflight result struct; `BrokerCost` reused as-is.
- **`backend/pdp/instruments/models.py` + `loader.py`**: add `freeze_qty` column, populate from
  the Dhan scrip master when present (fallback: per-underlying settings map).
- **`backend/pdp/broker_sync/client.py`**: reuse `fetch_funds()` for available balance.
- **`backend/pdp/settings.py`**: `ORDER_PREFLIGHT_ENABLED` (default True), `MARGIN_CHECK_ENABLED`
  (gated), `MARGIN_BUFFER_PCT` (default 5.0).
- **`backend/alembic/`**: migration adding `instruments.freeze_qty`.
- **`docs/RUNBOOK.md`**: new section — pre-flight checks and how to read a blocked order.
