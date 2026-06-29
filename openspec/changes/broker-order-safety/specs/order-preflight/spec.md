## ADDED Requirements

### Requirement: Preflight gate before live order placement
`OrderRouter` SHALL run a preflight check before dispatching any order to `DhanBroker`, and SHALL
NOT place a live order when preflight returns a hard failure.

#### Scenario: Preflight runs ahead of the live broker
- **WHEN** `OrderRouter.place_order` is called with `LIVE=1`, `BROKER=dhan`, and creds present
- **THEN** the preflight check runs before `DhanBroker.place()`
- **AND** the order is only sent to Dhan when the preflight result is `ok=True`

#### Scenario: Hard failure blocks the send
- **WHEN** preflight returns `ok=False` with a margin or lot/freeze violation in live mode
- **THEN** no order is sent to Dhan
- **AND** the response reports the order as rejected with the `violations` list

#### Scenario: Paper mode is advisory only
- **WHEN** `OrderRouter.place_order` runs in paper mode (default) and preflight returns `ok=False`
- **THEN** the preflight result is logged and attached to the response
- **AND** the paper order is still placed

---

### Requirement: Live Dhan margin check with basket routing
The system SHALL compute required margin via the Dhan margin API, routing a single leg to the
single-order endpoint and two-or-more legs to the basket (multi) endpoint, and SHALL compare the
required margin against available funds before allowing a live send.

#### Scenario: Single leg uses the single-order endpoint
- **WHEN** preflight evaluates one order
- **THEN** `MarginService` calls the single-order margin endpoint (`/margincalculator`)

#### Scenario: Multi-leg basket uses the multi endpoint
- **WHEN** preflight evaluates a basket of two or more legs (e.g. a strangle entry)
- **THEN** `MarginService` calls the basket margin endpoint (`/margincalculator/multi`) in one call

#### Scenario: Insufficient margin blocks a live order
- **WHEN** required margin exceeds available balance times `(1 − MARGIN_BUFFER_PCT/100)` in live mode
- **THEN** preflight returns `ok=False` with an `insufficient_margin` violation
- **AND** no order is sent to Dhan

---

### Requirement: Dhan HTTP-200 error responses are treated as failures
The system SHALL treat a Dhan margin response that returns HTTP 200 with an error payload as a
failure rather than a successful zero-margin result.

#### Scenario: 200 with error payload is a failure
- **WHEN** the Dhan margin endpoint returns HTTP 200 with `status` failure or an error message
- **THEN** `MarginService` raises/flags a margin-check failure
- **AND** in live mode the order is blocked rather than treated as requiring zero margin

#### Scenario: Response parsing accepts both key cases
- **WHEN** a successful margin response uses snake_case or camelCase field names
- **THEN** the parser reads the required-margin value correctly in either case

---

### Requirement: Lot-size and freeze-quantity validation
The system SHALL reject an order whose quantity is not a whole multiple of the instrument lot size
or whose quantity exceeds the instrument freeze quantity.

#### Scenario: Non-lot-multiple quantity is rejected
- **WHEN** an order quantity is not an integer multiple of the instrument `lot_size`
- **THEN** preflight returns `ok=False` with a `lot_multiple` violation

#### Scenario: Quantity above freeze limit is rejected
- **WHEN** an order quantity exceeds the instrument `freeze_qty`
- **THEN** preflight returns `ok=False` with a `freeze_exceeded` violation

#### Scenario: Missing freeze reference does not block
- **WHEN** no `freeze_qty` is known for the symbol from the master or the settings fallback
- **THEN** the freeze check is skipped with a one-time warning and does not block the order

---

### Requirement: Pre-trade charge estimate
The system SHALL attach an estimated charge breakdown to the preflight result before the order is
placed, reusing the existing live charges calculator.

#### Scenario: Charge estimate present on preflight
- **WHEN** preflight evaluates an order
- **THEN** the result includes a `charge_estimate` with the same component breakdown produced by
  the existing `ChargesCalculator` (brokerage, stt, exchange, sebi, stamp, gst)

---

### Requirement: Credential gating of the margin check
The system SHALL skip the margin portion of preflight, with a logged advisory, when Dhan
credentials are absent, while still running lot/freeze validation and the charge estimate.

#### Scenario: No credentials skips margin only
- **WHEN** `MARGIN_CHECK_ENABLED` is true but no Dhan credentials are configured
- **THEN** a `margin_check_skipped` advisory is logged
- **AND** lot/freeze validation and the charge estimate still run and can still block a live order
