## ADDED Requirements

### Requirement: A roll SHALL be all-or-nothing

`_roll_leg` SHALL resolve every precondition for the reopen — spot price, database session, the new
instrument, and the new leg's premium against `roll_target_min_prem` — **before** closing the
existing short or its matching hedge. When any precondition is unmet, the roll SHALL emit its
`skipped_*` outcome and leave the existing short and hedge open and unchanged.

#### Scenario: Spot price unavailable

- **WHEN** a roll triggers while the last spot price is unknown
- **THEN** the outcome `skipped_no_spot` is emitted, the short remains open, and the matching hedge remains open

#### Scenario: No instrument at the target strike

- **WHEN** the target OTM strike resolves to no instrument
- **THEN** the outcome `no_instrument` is emitted and no position is closed

#### Scenario: Target premium too low

- **WHEN** the target strike's premium is below `roll_target_min_prem`
- **THEN** the outcome `skipped_low_prem` is emitted and no position is closed

#### Scenario: Successful roll

- **WHEN** every precondition is met
- **THEN** the old short and its hedge close, the new short opens at the target strike, and one `ROLLED result=ok` event is emitted

#### Scenario: A skipped roll never leaves the book unhedged

- **WHEN** any `skipped_*` outcome is emitted
- **THEN** the number of open hedge legs is unchanged from before the roll attempt

### Requirement: The roll trigger SHALL be evaluated and claimed atomically

The check that a security is not already rolling and the claim that marks it as rolling SHALL occur
as one indivisible step under that security's lock. A concurrent tick for the same security SHALL
observe the claim and return without initiating a second roll.

#### Scenario: Two ticks race on the same security

- **WHEN** two ticks for the same security both satisfy the roll-trigger premium condition and are processed concurrently
- **THEN** exactly one roll executes and the other returns without placing an order

#### Scenario: The claim is released on failure

- **WHEN** a roll raises an exception
- **THEN** the security's rolling claim is released and a subsequent tick may roll it

### Requirement: Closing a leg SHALL be serialised against opening the same security

`_close_short_leg`, `_close_hedge_leg` and `_close_momentum_leg` SHALL hold the per-security lock
across the sequence that reads the broker net quantity and places the closing order — the same lock
held by the open path. No open and close for one security SHALL interleave between the read and the
place.

#### Scenario: Concurrent open and close on one security

- **WHEN** an open and a close for the same security are dispatched concurrently
- **THEN** one completes fully before the other reads the broker net quantity

#### Scenario: Locks are per security

- **WHEN** a close on one security is in progress
- **THEN** an open on a different security proceeds without waiting

### Requirement: At most one open leg SHALL exist per security

The strategy SHALL maintain at most one `OpenLeg` per `security_id` across its short, hedge and
momentum lists. A close SHALL reduce the broker position by that leg's own lot count rather than by
the security's entire net quantity. An attempt to track a second leg for a security that already has
one SHALL raise and emit a critical event.

#### Scenario: Close reduces only this leg's lots

- **WHEN** a leg of 4 lots is closed for a security whose broker net quantity is 4 lots
- **THEN** the closing order is for 4 lots

#### Scenario: Duplicate leg is rejected

- **WHEN** the strategy attempts to append an `OpenLeg` for a `security_id` already present in any leg list
- **THEN** the attempt raises, a critical event is emitted, and no order is placed

#### Scenario: Leg removal is unambiguous

- **WHEN** a leg is closed
- **THEN** no leg for that `security_id` remains in any leg list

### Requirement: In-memory leg state SHALL be reconciled against the broker on every state read

`state()` SHALL compare, per security, the total lots held across all in-memory leg lists against the
broker's net quantity, and SHALL emit a `LEG_STATE_DIVERGED` critical event when they disagree. A
position that exists at the broker but in no leg list SHALL be reported.

#### Scenario: A tracked leg matches the broker

- **WHEN** in-memory lots equal the broker net quantity for every security
- **THEN** no divergence event is emitted

#### Scenario: A position exists at the broker but in no leg list

- **WHEN** the broker holds an open position for a security absent from every leg list
- **THEN** a `LEG_STATE_DIVERGED` critical event names that security and its net quantity

#### Scenario: In-memory lots exceed the broker's

- **WHEN** a leg list reports more lots than the broker holds for that security
- **THEN** a `LEG_STATE_DIVERGED` critical event carries both quantities

### Requirement: Square-off SHALL close positions the in-memory lists do not know about

`_close_all` SHALL enumerate the broker's open positions for the strategy's securities and close
every one of them, including positions absent from the in-memory leg lists, emitting a critical event
per orphan closed. Square-off SHALL NOT depend solely on the in-memory leg lists.

#### Scenario: An orphaned position is squared off

- **WHEN** square-off runs while the broker holds an open position that no leg list references
- **THEN** that position is closed and a critical event names it

#### Scenario: Square-off is complete

- **WHEN** square-off completes
- **THEN** the broker reports zero open positions for every security the strategy traded that day
