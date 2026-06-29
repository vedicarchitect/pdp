## 1. Settings + reference data

- [x] 1.1 Add to `pdp/settings.py`: `ORDER_PREFLIGHT_ENABLED` (bool, default True),
  `MARGIN_CHECK_ENABLED` (bool, default False), `MARGIN_BUFFER_PCT` (float, default 5.0),
  `MARGIN_FAILOPEN` (bool, default False), `FREEZE_QTY_BY_UNDERLYING` (dict, default for
  NIFTY/BANKNIFTY/SENSEX)
- [x] 1.2 Add `freeze_qty` (Integer, nullable) to `pdp/instruments/models.py:Instrument`
- [x] 1.3 Alembic migration adding `instruments.freeze_qty`
- [x] 1.4 Populate `freeze_qty` in `pdp/instruments/loader.py:parse_dhan_csv` when the master
  column is present (graceful when absent)

## 2. MarginService (Dhan margin API)

- [x] 2.1 New `pdp/orders/margin.py` with `MarginService`, constructed with the dhanhq client;
  `None` when uncredentialed (mirror the `dhan_broker` instantiation gate)
- [x] 2.2 `_normalise_success_response(resp)` — flag a 200 body with `status` failure /
  `errorType` / `errorMessage` as a failure (port from `openalgo/broker/dhan/api/margin_api.py`)
- [x] 2.3 `required_margin(orders)` — route `len==1 → /margincalculator`,
  `len>=2 → /margincalculator/multi`; all SDK calls via `asyncio.to_thread`
- [x] 2.4 `parse_basket_margin_response` — read required margin from snake_case OR camelCase keys
- [x] 2.5 Unit-test the parser and the single/basket routing with recorded fixtures

## 3. Preflight in OrderRouter

- [x] 3.1 Add a `PreflightResult` struct (`pdp/orders/models.py`):
  `ok`, `margin_required`, `margin_available`, `charge_estimate`, `violations: list[str]`
- [x] 3.2 `OrderRouter._preflight(orders)` — runs lot/freeze validation, charge estimate, and
  (when enabled + credentialed) the margin check; compares against `BrokerFund.available_balance`
  via the existing `broker_sync` funds read
- [x] 3.3 Wire `_preflight` into `place_order` before the `DhanBroker.place()` branch; block in
  live on `ok=False`, attach-and-proceed in paper
- [x] 3.4 Reuse `ChargesCalculator` from `pdp/orders/paper.py` for the estimate (no new cost model)
- [x] 3.5 Honour `MARGIN_FAILOPEN` on margin-API exception/timeout (default fail-closed in live)

## 4. Validation + archive

- [x] 4.1 `task openspec:validate -- broker-order-safety --strict` passes
- [x] 4.2 `task test` green for new margin/preflight unit tests
- [x] 4.3 `docs/RUNBOOK.md` — add the pre-flight checks section (how to read a blocked order)
- [ ] 4.4 Owner paper-run: confirm a strangle basket gets one multi-margin call and a charge
  estimate, with no live order sent in paper
