## Context

The multi-day backtest (`backtest_multiday.py`) needs OHLCV for **expired** weekly NIFTY
option contracts. The live `instruments` table only holds active contracts; once a weekly
expires (NIFTY expiry = Tuesday) Dhan drops it from the security master, so its
`security_id` vanishes and those legs cannot be priced. The prior fallback called Dhan's
`expired_options_data` live on every run and returned zero bars for historical windows due
to two defects (`expiry_code=0`, and selecting the `ce`/`pe` side before unwrapping the
nested `data` payload). PDP already uses MongoDB as its bar warehouse (`market_bars` is a
time-series collection seeded/persisted by the IndicatorEngine warm-up), so the natural
home for expired-option bars is MongoDB — not DuckDB (the Abi-project approach, explicitly
rejected here).

## Goals / Non-Goals

**Goals:**
- Durable MongoDB warehouse of expired-option bars, mirroring the `market_bars` pattern.
- Idempotent backfill from the Dhan rolling-option API.
- Backtest reads from MongoDB, with live-API fallback only on cache miss.
- Fix the `expiry_code` and payload-unwrap defects.

**Non-Goals:**
- Full 5-year / ATM±10 / WEEK+MONTH / codes 1-3 warehouse (start strategy-minimal; widen
  later via wider CLI args).
- Fixed-strike reconstruction — the rolling-option series is ATM-relative by design.
- Live-trading integration or IndicatorEngine warm-up parity (out of scope).

## Decisions

- **Dedicated collection `expired_option_bars` (vs reusing `market_bars`).** The rolling
  series is keyed by ATM-relative label, not `security_id`. A separate time-series
  collection keeps `market_bars` clean (real ids) and preserves the full
  `expiry_flag / expiry_code / strike_label / option_type` identity. Alternative
  (synthetic `security_id` strings in `market_bars`) overloads one field and mixes two
  data models — rejected.
- **Reuse the `market_bars` time-series shape** (`ts` timeField, `metadata` metaField,
  `granularity: seconds`) so reads/writes mirror `warmup._fetch_from_mongo` /
  `_persist_bars`.
- **`expiry_code=1`** (nearest expiry from `from_date`), confirmed against the Abi
  reference pipeline. `0` means nearest-from-today and yields no data for historical days.
- **Unwrap nested `data` in a loop before side selection.** Real payload is
  `data["data"]["ce"|"pe"]`; unwrapping after picking the side fails silently.
- **Manual dedup, normalized to aware UTC.** Time-series collections cannot carry a unique
  index, and pymongo returns stored `ts` as naive UTC — so the dedup set normalizes fetched
  timestamps to aware UTC and inserts only new bars. Gives idempotency without a unique key.
- **Strategy-minimal backfill scope** (WEEK, code 1, ATM-1/ATM/ATM+1, 5m, ~12 months) as
  the default; widened by CLI flags.

## Risks / Trade-offs

- **ATM-relative approximation** → The series re-evaluates ATM per bar, so prices are
  rolling ATM±N rather than the exact fixed strike held. Acceptable for intraday
  estimation; documented as a caveat.
- **No unique index on the time-series collection** → relies on the manual aware-UTC dedup;
  mitigated by a smoke test asserting a second backfill inserts zero bars.
- **Data-API rate limit (5 req/sec) and 30-day cap** → backfill chunks the range and pauses
  between calls; minimal scope keeps total calls low.
- **Reliable-day path still fetches all active strikes live** → pre-existing and unchanged;
  not addressed by this change.

## Migration Plan

1. Deploy collection creation (`init_collections`) — idempotent, safe on existing deployments.
2. Run `scripts/backfill_expired_options.py` to populate the warehouse.
3. Backtest automatically reads from MongoDB; no data migration of existing collections.
4. Rollback: drop `expired_option_bars`; the backtest fallback still functions via the live
   API (now with the corrected `expiry_code`/unwrap fixes).
