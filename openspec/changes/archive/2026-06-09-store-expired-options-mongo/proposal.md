## Why

Expired NIFTY weekly option contracts disappear from the instruments table once they
expire (Dhan drops them from the security master), so the multi-day backtest cannot price
those legs and historical expired days returned zero trades. We need a durable store of
expired-option OHLCV bars in MongoDB — PDP's single warehouse — instead of re-hitting the
rate-limited Dhan data API on every run (and instead of the rejected DuckDB approach).

## What Changes

- Add a MongoDB time-series collection `expired_option_bars` storing ATM-relative rolling
  option bars (`open/high/low/close/volume/oi/iv`) with metadata
  `underlying / expiry_flag / expiry_code / strike_label / option_type / timeframe`.
- Add a backfill CLI `scripts/backfill_expired_options.py` that warehouses bars from
  Dhan's `expired_options_data` (`/v2/charts/rollingoption`) in ≤30-day chunks,
  idempotently.
- Change the backtest's expired-contract path to read from MongoDB first and fall back to
  the live API (persisting the result) only on a cache miss.
- Fix two defects in the expired-data fetch: use `expiry_code=1` (nearest expiry from the
  `from_date`, not from today) and unwrap the double-nested `data["data"]["ce"|"pe"]`
  payload before selecting the option side.

## Capabilities

### New Capabilities
- `expired-option-bars`: MongoDB storage, backfill, and read-path for OHLCV bars of expired
  option contracts that no longer exist in the instrument registry.

### Modified Capabilities
<!-- No spec-level requirement changes to existing capabilities; backtest behaviour is
     covered by the new capability's read-path requirement. -->

## Impact

- New code: `scripts/backfill_expired_options.py`.
- Modified code: `src/pdp/mongo/collections.py` (new collection + accessor),
  `backtest_multiday.py` (`fetch_opt_expired` read path + `_persist_expired`).
- New MongoDB collection `expired_option_bars` (time-series; no schema migration to
  existing collections).
- External dependency: Dhan `expired_options_data` data API (rate-limited 5 req/sec, up to
  5 years history, ≤30 days/call).
