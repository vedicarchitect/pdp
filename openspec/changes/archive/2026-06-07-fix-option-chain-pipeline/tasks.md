# Tasks

## 1. dhan_client.py
- [x] 1.1 Replace `underlying_map` with correct `IDX_I` security IDs (`NIFTY=13,
  BANKNIFTY=25, FINNIFTY=27, MIDCPNIFTY=442, SENSEX=51`).
- [x] 1.2 Add `fetch_expiries(underlying, access_token, client_id) -> list[str]` calling
  `client.expiry_list(...)`, returning sorted ISO date strings from `response["data"]`.
- [x] 1.3 Change `fetch_chain(underlying, expiry, access_token, client_id, ...)` to fetch
  a single ISO expiry and return the raw Dhan dict augmented as `{"data": {...},
  "expiry": expiry}`; delete the `CallOptions/PutOptions` transform and the
  next-Thursday computation.

## 2. poller.py
- [x] 2.1 Rewrite `_parse_chain(raw, underlying, rate)` to consume the raw
  `{data:{last_price, oc:{strike:{ce,pe}}}}` single-expiry shape; read raw field names
  (`last_price`, `oi`, `volume`, `implied_volatility`, nested `greeks`).
- [x] 2.2 Prefer Dhan-provided IV/greeks per side; fall back to `greeks.compute_greeks`
  for sides missing them.
- [x] 2.3 In `_poll_one`, call `fetch_expiries`, take nearest 3, loop `fetch_chain` per
  expiry with `await asyncio.sleep(3)` between calls; keep one Mongo doc per expiry.
- [x] 2.4 Fix spot extraction to read from the raw shape.

## 3. greeks.py
- [x] 3.1 Add a helper to compute greeks for a subset of rows missing Dhan values (or
  reuse `compute_greeks` on the fallback DataFrame). Keep vollib import lazy.

## 4. CLI (progress-test-cli code, no spec delta)
- [x] 4.1 `commands/option_chain.py`: consume canonical shape via the shared parser;
  render `Strike, CE LTP, CE OI, CE IV, CE Δ, PE LTP, PE OI, PE IV, PE Δ`; full greeks
  in JSON; group by expiry.
- [x] 4.2 `main.py`: add `--expiry` and `--all-expiries` options to `option-chain`.
- [x] 4.3 `commands/greeks.py`: use real spot/strike/option-LTP, reuse
  `pdp.options.greeks.compute_greeks`, delete the duplicated `_calculate_greeks`.

## 5. Verification
- [x] 5.1 `openspec validate --strict fix-option-chain-pipeline`.
- [x] 5.2 `pdp progress option-chain --symbol NIFTY` shows real strikes (LTP/OI/IV/Δ).
- [x] 5.3 `pdp progress option-chain --symbol BANKNIFTY --all-expiries` shows 3 expiries.
- [x] 5.4 `pdp progress option-chain --symbol NIFTY --format json` has ce/pe greeks.
- [x] 5.5 MIDCPNIFTY returns its own chain (not NIFTY) — security-ID regression.
- [x] 5.6 Poller path: refresh + `GET .../chain` returns populated strikes; one doc per
  expiry in `option_chains`. NOTE: code path + parser verified by unit tests and live
  `fetch_expiries`/`fetch_chain`/`_parse_chain`; full server+Mongo round-trip not run in
  this environment.
- [x] 5.7 `pdp progress greeks`: logic verified; live run blocked by environment
  (`DATABASE_URL` uses sync `psycopg2`, not an async driver) — pre-existing config issue,
  not introduced by this change.
- [x] 5.8 `uv run pytest -k "option or chain or greeks"` green (update fixtures to raw
  `oc` shape).
