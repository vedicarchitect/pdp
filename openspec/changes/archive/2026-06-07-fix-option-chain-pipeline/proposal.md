## Why

The options-chain pipeline is non-functional end-to-end. Three compounding bugs:

1. **Wrong index security IDs/segment.** `dhan_client.py` maps `NIFTY=1/NFO`,
   `BANKNIFTY=4/NFO`, `MIDCPNIFTY=13/NFO`, etc. Dhan requires the `IDX_I` segment with
   IDs `NIFTY=13, BANKNIFTY=25, FINNIFTY=27, MIDCPNIFTY=442, SENSEX=51`. `13` is
   actually NIFTY-50, so MIDCPNIFTY silently returns NIFTY.
2. **Three incompatible payload shapes.** `fetch_chain` transforms the SDK response
   into `{CallOptions, PutOptions}` by treating `data` as a list — but Dhan returns
   `data` as a dict `{last_price, oc:{strike:{ce,pe}}}`, so the transform never matches
   and `fetch_chain` always returns empty. The poller's `_parse_chain` expects the raw
   shape (and a per-strike `expiry_date` that does not exist), and the CLI expects a
   third `Strike/Bid/Ask` shape.
3. **Single hardcoded weekly expiry, wrong date format.** `fetch_chain` computes "next
   Thursday" formatted as `%d-%b-%Y` instead of using `expiry_list` + ISO dates, so
   weekly/monthly coverage is impossible.

The result: empty chains, no greeks, broken CLI. We also need the `progress` CLI to
actually verify the fix.

## What Changes

- Correct the index security-ID/segment map to `IDX_I` values.
- Add `fetch_expiries()` (Dhan `expiry_list`) and change `fetch_chain()` to fetch a
  single ISO expiry and return one canonical raw shape.
- Drive the nearest 3 expiries in the poller (3 s rate-limit between calls), parse the
  raw `oc` dict, and prefer Dhan-provided IV/greeks with a `vollib` fallback.
- Rewrite the CLI `option-chain` command to render real strikes (LTP/OI/IV/greeks) with
  `--expiry` / `--all-expiries`, reusing the shared parser.
- Fix the CLI `greeks` command to use real spot/strike/option-LTP via the shared
  `compute_greeks` helper.

## Capabilities

### Modified Capabilities
- `options-analytics`: corrected ingest (security IDs, `expiry_list`, single canonical
  payload, nearest-3 expiries) and IV/Greeks sourcing (Dhan-provided + vollib fallback).

### New Capabilities
<!-- None. -->

## Impact

- Code (options engine): `src/pdp/options/{dhan_client,poller,greeks}.py`.
- Code (CLI bug-fix, no spec change): `src/pdp/cli/progress/commands/{option_chain,
  greeks}.py`, `src/pdp/cli/progress/main.py`. These belong to the `progress-test-cli`
  capability, whose change (`add-progress-test-cli`) is complete but not yet archived,
  so the fixes make the existing CLI code work against the corrected options engine
  rather than introducing new requirements.
- No DB schema or REST contract changes; the stored snapshot document shape is unchanged.
- Behaviour change: chains now return data; greeks may originate from Dhan when present.
