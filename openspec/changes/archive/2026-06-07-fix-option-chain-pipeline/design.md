## Context

The Dhan SDK exposes two relevant calls:

- `dhan.expiry_list(under_security_id, under_exchange_segment)` → `{status, data:[ISO
  date str, ...]}`.
- `dhan.option_chain(under_security_id, under_exchange_segment, expiry)` →
  `{status, data:{last_price, oc:{"<strike>":{ce:{...}, pe:{...}}}}}` for **one**
  expiry. Each `ce`/`pe` carries raw fields `last_price, oi, volume,
  implied_volatility` and a nested `greeks:{delta,gamma,theta,vega}`. Rate limit: one
  unique option-chain request per 3 seconds.

The current code contradicts this contract in three places (producer + two consumers),
so nothing works.

## Goals / Non-Goals

- **Goals:** one canonical payload shape; correct `IDX_I` security IDs; multi-expiry
  (nearest 3) coverage; Dhan-provided greeks with vollib fallback; working CLI for
  verification.
- **Non-Goals:** changing the stored Mongo document schema, REST contracts, the
  poll-interval/market-hours logic, or the max-pain/PCR algorithms.

## Decisions

### Canonical payload shape
`fetch_chain(underlying, expiry, ...)` returns the **raw** Dhan dict augmented with the
requested expiry: `{"data": {...}, "expiry": "<ISO>"}`. Both the poller and the CLI
consume this single shape through a shared `_parse_chain(raw, underlying, rate)` that
yields a list of strike dicts (`{expiry, strike, ce:{...}, pe:{...}}`). The
`CallOptions/PutOptions` transform is deleted.

### Security IDs
`underlying_map = {NIFTY:(13,"IDX_I"), BANKNIFTY:(25,"IDX_I"), FINNIFTY:(27,"IDX_I"),
MIDCPNIFTY:(442,"IDX_I"), SENSEX:(51,"IDX_I")}`. Source: Dhan instrument table.

### Expiry selection
Poller and CLI call `fetch_expiries`, sort ascending, take `[:3]`. Per expiry: one
`option_chain` call, `await asyncio.sleep(3)` between calls to honour the rate limit.
One Mongo doc per `(underlying, expiry)` (unchanged write loop).

### Greeks sourcing
For each side, if `implied_volatility` and a complete `greeks` block are present and
non-null, use them. Otherwise fall back to the existing `greeks.compute_greeks` vollib
path for the missing rows. T≤0 and NaN handling (clip IV to [0.01,5.0], NaN greeks→0)
remain in the vollib path.

### CLI greeks (positions)
Resolve true spot (from the option-chain `last_price`) and parse strike + option type
from the instrument symbol; use option LTP (not `unrealized_pnl`) as the price. Reuse
`pdp.options.greeks.compute_greeks`; delete the duplicated `_calculate_greeks`.

## Risks / Trade-offs

- **Rate limit:** 2 underlyings × 3 expiries × 3 s = 18 s < 30 s poll interval — fits.
  More underlyings/expiries would need a longer interval.
- **Greeks divergence:** Dhan greeks may differ slightly from vollib; acceptable since
  Dhan is the broker source of truth. Fallback keeps coverage when Dhan omits them.

## Migration Plan

Pure code fix; no data migration. Old (broken) snapshots simply age out via the
existing TTL index.

## Open Questions

None.
